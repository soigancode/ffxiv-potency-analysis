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
    actions = Path(__file__).parents[2] / "data/machinist/7.55/actions.json"
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
    "machinist/7.55/combat_profile.json", "machinist/weapon_delays.json",
    "machinist/7.55/pet_scaling.json", "machinist/7.55/actions.json",
    "consumables/food/example.json", "encounters/1084/penalties.json",
    "raid_effects/7.55.json",
])
def test_reference_data_changes_invalidate(saved_log, tmp_path, monkeypatch, relative) -> None:
    directory, actions = saved_log
    package = tmp_path / "installed-package"
    monkeypatch.setattr(cache, "_reference_roots", lambda: (package / "data", package / "data"))
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
    actions = root / "machinist/7.55/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_bytes(original_actions.read_bytes())
    before = cache._fingerprint(directory, actions)
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    assert cache._fingerprint(directory, actions) != before
    changed = cache._fingerprint(directory, actions)
    actions.write_text(actions.read_text() + " ")
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
    actions = Path(__file__).parents[2] / "data" / job / "7.55/actions.json"
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
    root = actions.parent.parent.parent
    for folder in ("raid_effects", "raid_buffs"):
        if (root / folder).exists():
            shutil.copytree(root / folder, moved_actions.parents[2] / folder)
    assert cache._fingerprint(directory, actions) == cache._fingerprint(moved, moved_actions)
