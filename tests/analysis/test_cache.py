"""Persistent reuse, invalidation and recovery against real player data."""

import json
import zipfile
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze as analyzer
from ffxiv_potency.analysis import cache


@pytest.fixture
def saved_log(tmp_path: Path) -> tuple[Path, Path]:
    fixture = Path(__file__).parents[1] / "fixtures/logs/mch_enuo_sample.zip"
    with zipfile.ZipFile(fixture) as archive:
        archive.extractall(tmp_path)
    directory = next(tmp_path.rglob("fight.json")).parent
    actions = Path(__file__).parents[2] / "data/jobs/mch/7.4/actions.json"
    return directory, actions


def test_reuses_typed_result_and_recovers_corruption(saved_log, monkeypatch) -> None:
    directory, actions = saved_log
    actual = analyzer._analyze_saved_fight
    calls = []

    def calculate(*args):
        calls.append(1)
        return actual(*args)

    monkeypatch.setattr(analyzer, "_analyze_saved_fight", calculate)
    first = analyzer.analyze_saved_fight(directory, actions)
    assert analyzer.analyze_saved_fight(directory, actions) == first
    assert len(calls) == 1
    assert isinstance(first.actions, tuple)
    assert analyzer.analyze_saved_fight(directory, actions, use_cache=False) == first
    assert len(calls) == 2
    path = cache.cache_path(directory)
    document = json.loads(path.read_text())
    document["result"]["potency_min"] = "broken"
    path.write_text(json.dumps(document))
    assert analyzer.analyze_saved_fight(directory, actions) == first
    assert len(calls) == 3
    monkeypatch.setattr(cache, "ANALYZER_REVISION", cache.ANALYZER_REVISION + 1)
    assert analyzer.analyze_saved_fight(directory, actions) == first
    assert len(calls) == 4


@pytest.mark.parametrize("filename", [
    "fight.json", "damage-events.json", "checkpoint-context.json", "combatant-info-events.json",
    "rankings.json", "master-data.json", "cast-events.json", "buff-events.json",
    "encounter-damage-events.json",
])
def test_log_content_invalidates_even_with_same_stat(saved_log, filename) -> None:
    import os

    directory, actions = saved_log
    key = cache._fingerprint(directory, actions)
    path = directory / filename
    if path.exists():
        original = path.stat()
        payload = path.read_bytes()
        path.write_bytes(payload + b" ")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    else:
        path.write_text("{}")
    assert cache._fingerprint(directory, actions) != key


@pytest.mark.parametrize("relative", [
    "jobs/mch/combat_profiles/level_100.json", "jobs/mch/weapon_delays.json",
    "jobs/mch/7.4/pet_scaling.json", "jobs/mch/7.4/actions.json",
    "consumables/food/example.json", "encounters/1084/penalties.json",
    "raid_effects/7.55.json",
])
def test_reference_data_changes_invalidate(saved_log, tmp_path, monkeypatch, relative) -> None:
    directory, actions = saved_log
    package = tmp_path / "installed-package"
    monkeypatch.setattr(cache, "_reference_roots", lambda: (package / "data", package / "data"))
    monkeypatch.setattr(cache, "action_data_root", lambda _: package / "data")
    before = cache._fingerprint(directory, actions)
    path = package / "data" / relative
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    added = cache._fingerprint(directory, actions)
    assert added != before
    path.write_text('{"updated": true}')
    assert cache._fingerprint(directory, actions) != added
    path.unlink()
    assert cache._fingerprint(directory, actions) == before


@pytest.mark.parametrize("relative", ["raid_effects/7.55.json", "raid_buffs/7.55/effects.json"])
def test_external_raid_override_invalidates(saved_log, tmp_path, relative) -> None:
    directory, original_actions = saved_log
    root = tmp_path / "custom"
    actions = root / "jobs/mch/7.4/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_bytes(original_actions.read_bytes())
    before = cache._fingerprint(directory, actions)
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    assert cache._fingerprint(directory, actions) != before
    changed = cache._fingerprint(directory, actions)
    document = json.loads(actions.read_text())
    document["actions"][0]["potency"]["base"] += 1
    actions.write_text(json.dumps(document))
    assert cache._fingerprint(directory, actions) != changed


def test_unwritable_cache_does_not_block_analysis(saved_log, monkeypatch) -> None:
    directory, actions = saved_log
    expected = analyzer.analyze_saved_fight(directory, actions, use_cache=False)

    def denied(*args, **kwargs):
        raise PermissionError("read-only log")

    monkeypatch.setattr(cache.tempfile, "NamedTemporaryFile", denied)
    assert analyzer.analyze_saved_fight(directory, actions) == expected


@pytest.mark.parametrize("fixture,job", [
    ("brd_dancing_mad.zip", "bard"),
    ("mch_lindwurm_ii_opening_queens.zip", "machinist"),
])
def test_nested_job_results_round_trip(tmp_path, fixture, job) -> None:
    with zipfile.ZipFile(Path(__file__).parents[1] / "fixtures/logs" / fixture) as archive:
        archive.extractall(tmp_path)
    actions = Path(__file__).parents[2] / "data" / "jobs" / {"bard": "brd", "machinist": "mch"}[job] / "7.4/actions.json"
    for path in tmp_path.rglob("fight.json"):
        result = analyzer.analyze_saved_fight(path.parent, actions, use_cache=False)
        restored = cache._decode(json.loads(json.dumps(cache._encode(result))), type(result))
        assert restored == result
        assert restored.pps_min == result.pps_min


def test_cleared_and_redownloaded_log_reuses_calculation(saved_log, tmp_path, monkeypatch) -> None:
    import shutil

    from ffxiv_potency import cli

    original, actions = saved_log
    logs = tmp_path / "downloads"
    directory = logs / "report/fight-1/source-2"
    shutil.copytree(original, directory)
    expected = analyzer.analyze_saved_fight(directory, actions)
    path = cache.cache_path(directory)
    assert path.is_file()
    assert not (directory / cache.CACHE_FILENAME).exists()
    assert cli.main(["clear", "logs", "--output", str(logs), "--yes"]) == 0
    assert path.is_file() and not directory.exists()
    shutil.copytree(original, directory)

    def unexpected(*args):
        raise AssertionError("identical re-download should reuse calculation")

    monkeypatch.setattr(analyzer, "_analyze_saved_fight", unexpected)
    assert analyzer.analyze_saved_fight(directory, actions) == expected
    assert cli.main(["clear", "cache", "--output", str(logs), "--yes"]) == 0
    assert not path.exists() and directory.is_dir()


def test_fingerprint_survives_log_and_action_relocation(saved_log, tmp_path) -> None:
    import shutil

    directory, actions = saved_log
    moved = tmp_path / "relocated/report/fight-1/source-2"
    shutil.copytree(directory, moved)
    moved_actions = tmp_path / "relocated-actions/machinist/7.55/actions.json"
    moved_actions.parent.mkdir(parents=True)
    moved_actions.write_bytes(actions.read_bytes())
    # Copy the action-root raid data too, since it participates in the inputs.
    root = cache.action_data_root(actions)
    for folder in ("raid_effects", "raid_buffs"):
        if (root / folder).exists():
            shutil.copytree(root / folder, cache.action_data_root(moved_actions) / folder)
    assert cache._fingerprint(directory, actions) == cache._fingerprint(moved, moved_actions)


def test_gear_override_has_separate_cache_identity(saved_log) -> None:
    directory, actions = saved_log
    savage = analyzer.analyze_saved_fight(directory, actions, gear="savage_7_4")
    relic = analyzer.analyze_saved_fight(directory, actions, gear="relic_7_55")
    assert savage.gear_id == "savage_7_4"
    assert relic.gear_id == "relic_7_55"
    assert savage.gear_source == relic.gear_source == "user-selected"
    assert savage.luck_baseline != relic.luck_baseline
    assert analyzer.analyze_saved_fight(directory, actions, gear="relic_7_55") == relic


def test_unchanged_jobguide_update_reuses_calculation(saved_log, tmp_path, monkeypatch) -> None:
    import shutil

    import httpx

    from ffxiv_potency.jobguide.snapshot import update_job_guide

    directory, _ = saved_log
    checkout = tmp_path / "checkout"
    shutil.copytree(Path("data"), checkout / "data")
    fixture = Path("tests/fixtures/jobguide/mch_full_7_5.html").read_text()
    monkeypatch.chdir(checkout)
    actions = checkout / "data/jobs/mch/7.4/actions.json"
    monkeypatch.setattr(cache, "_reference_roots", lambda: (checkout / "data", checkout / "data"))
    actual = analyzer._analyze_saved_fight
    calls = []

    def calculate(*args):
        calls.append(1)
        return actual(*args)

    monkeypatch.setattr(analyzer, "_analyze_saved_fight", calculate)
    expected = analyzer.analyze_saved_fight(directory, actions)
    update_job_guide(
        job="machinist", patch="7.56", output_root=checkout / "data",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=fixture)),
    )
    assert analyzer.analyze_saved_fight(directory, actions) == expected
    assert len(calls) == 1
    update_job_guide(
        job="machinist", patch="7.56", output_root=checkout / "data",
        transport=httpx.MockTransport(lambda _: httpx.Response(
            200, text=fixture.replace("potency of 660.", "potency of 670.", 1),
        )),
    )
    analyzer.analyze_saved_fight(directory, actions)
    assert len(calls) == 2


def test_reference_provenance_and_formatting_do_not_invalidate(saved_log, tmp_path, monkeypatch):
    import shutil

    directory, original_actions = saved_log
    root = tmp_path / "references"
    shutil.copytree(Path("data/jobs/mch"), root / "jobs/mch")
    actions = root / "jobs/mch/7.4/actions.json"
    assert actions.read_bytes() == original_actions.read_bytes()
    patches = root / "patches.json"
    shutil.copyfile(Path("data/patches.json"), patches)
    monkeypatch.setattr(cache, "_reference_roots", lambda: (root, root))
    monkeypatch.setattr(cache, "reference_path", lambda *parts: root.joinpath(*parts))
    before = cache._fingerprint(directory, actions)
    document = json.loads(actions.read_text())
    document["source"] = {"retrieved_at": "new capture", "sha256": "new hash", "url": "new URL"}
    actions.write_text(json.dumps(document, sort_keys=True))
    manifest_path = root / "jobs/mch/datasets.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["last_capture"] = {"patch": "7.56", "source": document["source"]}
    manifest["action_sets"][0]["verified_through"] = "7.56"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    patch_data = json.loads(patches.read_text())
    patch_data["sources"]["7.56"] = "another citation"
    patches.write_text(json.dumps(patch_data, sort_keys=True))
    assert cache._fingerprint(directory, actions) == before
    manifest["action_sets"][0]["valid_until"] = "8.0"
    manifest_path.write_text(json.dumps(manifest))
    assert cache._fingerprint(directory, actions) != before
    manifest["action_sets"][0].pop("valid_until")
    manifest_path.write_text(json.dumps(manifest))
    assert cache._fingerprint(directory, actions) == before
    patch_data["starts"]["7.55"] = "2026-07-29T10:00:00Z"
    patches.write_text(json.dumps(patch_data))
    assert cache._fingerprint(directory, actions) != before
    patch_data["starts"]["7.55"] = "2026-07-28T10:00:00Z"
    patches.write_text(json.dumps(patch_data))
    assert cache._fingerprint(directory, actions) == before
    document["traits"][0]["description"].append("Changed trait effect")
    actions.write_text(json.dumps(document))
    assert cache._fingerprint(directory, actions) != before
