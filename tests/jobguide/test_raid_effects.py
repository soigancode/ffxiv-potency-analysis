"""Raid effect data is parsed from each official guide, not fixed in the crawler."""

import json
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.analysis.luck import _load_raid_effects
from ffxiv_potency.jobguide.raid_buffs import parse_raid_effects, update_raid_effects
from ffxiv_potency.raid_effects import resolve_effects


def _row(index: int, action: str, description: str) -> str:
    return (
        f'<tr id="pve_action__{index}"><td class="skill"><strong>{action}</strong></td>'
        f'<td class="content">{description}</td></tr>'
    )


def test_reuses_parsed_bard_and_crawls_unparsed_job_guides(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only patch 7.56"):
        update_raid_effects(tmp_path, "7.5")
    pages = {
        "dragoon": _row(
            1,
            "Battle Litany",
            "Increases critical hit rate of self and nearby party members by 10%.",
        ),
        "bard": "".join(
            [
                _row(
                    2,
                    "Battle Voice",
                    "Increases direct hit rate of self and all nearby party members by 20%.",
                ),
                _row(3, "Army's Paeon", "Grants Army's Paeon, increasing direct hit rate by 3%."),
                _row(
                    4,
                    "The Wanderer's Minuet",
                    "Grants the Wanderer's Minuet, increasing critical hit rate by 4%.",
                ),
            ]
        ),
        "dancer": _row(
            5,
            "Devilment",
            "Increases critical hit rate and direct hit rate by 20%. "
            "Party member designated as your Dance Partner will also receive the effect.",
        ),
        "scholar": _row(
            6, "Chain Stratagem", "Increases rate at which target takes critical hits by 10%."
        ),
    }

    requested = []

    def respond(request: httpx.Request) -> httpx.Response:
        job = request.url.path.rstrip("/").split("/")[-1]
        requested.append(job)
        return httpx.Response(200, text=pages[job])

    destination = update_raid_effects(tmp_path, "7.56", transport=httpx.MockTransport(respond))
    assert destination == tmp_path / "raid_effects/7.4.json"
    document = json.loads(destination.read_text())
    resolved = resolve_effects(document, tmp_path, "7.56")
    assert [effect["bonus"] for effect in resolved] == [
        0.10,
        0.10,
        0.20,
        0.03,
        0.02,
        0.20,
        0.20,
    ]
    assert requested == ["scholar", "dragoon"]
    assert (tmp_path / "raid_effects/sources/7.56/scholar.html").is_file()
    assert all("bonus" not in effect for effect in document["effects"] if effect["job"] in {"bard", "dancer"})
    actions = tmp_path / "machinist/7.56/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"patch": "7.56"}', encoding="utf-8")
    assert _load_raid_effects(actions) == resolved
    with pytest.raises(ValueError, match="one crit/DH rate"):
        parse_raid_effects(pages["dragoon"].replace("10%", "unknown"), "dragoon")
    with pytest.raises(ValueError, match="both crit and DH rates"):
        parse_raid_effects(pages["dancer"].replace("direct hit rate", "accuracy"), "dancer")


def _remaining_guide_response(request: httpx.Request, *, litany: int = 10) -> httpx.Response:
    job = request.url.path.rstrip("/").split("/")[-1]
    pages = {
        "scholar": _row(1, "Chain Stratagem", "Increases rate at which target takes critical hits by 10%."),
        "dragoon": _row(2, "Battle Litany", f"Increases critical hit rate by {litany}%."),
        "dancer": _row(3, "Devilment", "Increases critical hit rate and direct hit rate by 20%."),
    }
    return httpx.Response(200, text=pages[job])


def test_unchanged_raid_capture_keeps_original_version_and_cache_key(tmp_path: Path) -> None:
    from ffxiv_potency.analysis.cache import _fingerprint

    actions = tmp_path / "jobs/mch/7.4/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"patch":"7.56"}')
    transport = httpx.MockTransport(_remaining_guide_response)
    first = update_raid_effects(tmp_path, transport=transport)
    original = first.read_bytes()
    key = _fingerprint(tmp_path, actions)
    second = update_raid_effects(tmp_path, transport=transport)
    assert second == first == tmp_path / "raid_effects/7.4.json"
    assert second.read_bytes() == original
    assert _fingerprint(tmp_path, actions) == key
    manifest = json.loads((tmp_path / "raid_effects/datasets.json").read_text())
    assert len(manifest["effect_sets"]) == 1
    assert manifest["effect_sets"][0]["verified_through"] == "7.56"


def test_changed_inline_effect_retains_historical_values(tmp_path: Path) -> None:
    first = update_raid_effects(tmp_path, transport=httpx.MockTransport(_remaining_guide_response))
    original = first.read_bytes()
    changed = update_raid_effects(tmp_path, transport=httpx.MockTransport(
        lambda request: _remaining_guide_response(request, litany=11),
    ))
    assert changed == tmp_path / "raid_effects/7.56.json"
    assert first.read_bytes() == original
    rows = json.loads((tmp_path / "raid_effects/datasets.json").read_text())["effect_sets"]
    assert rows[0]["valid_until"] == "7.56"
    actions = tmp_path / "jobs/mch/7.4/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"patch":"7.56"}')
    old = _load_raid_effects(actions, played_patch="7.55")
    new = _load_raid_effects(actions, played_patch="7.56")
    assert next(row["bonus"] for row in old if row["action"] == "Battle Litany") == 0.10
    assert next(row["bonus"] for row in new if row["action"] == "Battle Litany") == 0.11


def test_bard_reference_uses_job_action_version_for_fight_patch(tmp_path: Path) -> None:
    import shutil

    from ffxiv_potency.jobguide.snapshot import update_job_guide

    root = tmp_path / "data"
    shutil.copytree(Path("data/jobs/brd"), root / "jobs/brd")
    html = Path("tests/fixtures/jobguide/brd_full_7_5.html").read_text()
    changed = html.replace("increasing critical hit rate by 2%.", "increasing critical hit rate by 4%.")
    assert changed != html
    update_job_guide(job="bard", patch="7.56", output_root=root,
                     transport=httpx.MockTransport(lambda _: httpx.Response(200, text=changed)))
    snapshot = update_raid_effects(root, transport=httpx.MockTransport(_remaining_guide_response))
    assert snapshot.name == "7.4.json"
    document = json.loads(snapshot.read_text())
    assert all("bonus" not in row for row in document["effects"] if row["job"] == "bard")
    old = resolve_effects(document, root, "7.55")
    new = resolve_effects(document, root, "7.56")
    assert next(row["bonus"] for row in old if row["action"] == "The Wanderer's Minuet") == 0.02
    assert next(row["bonus"] for row in new if row["action"] == "The Wanderer's Minuet") == 0.04


def test_invalid_raid_update_preserves_previous_files(tmp_path: Path) -> None:
    first = update_raid_effects(tmp_path, transport=httpx.MockTransport(_remaining_guide_response))
    original = first.read_bytes()
    manifest = tmp_path / "raid_effects/datasets.json"
    original_manifest = manifest.read_bytes()
    with pytest.raises(ValueError, match="expected one PvE"):
        update_raid_effects(tmp_path, transport=httpx.MockTransport(lambda _: httpx.Response(200, text="invalid guide")))
    assert first.read_bytes() == original
    assert manifest.read_bytes() == original_manifest


def test_devilment_reference_uses_dancer_action_version(tmp_path: Path) -> None:
    import shutil

    from ffxiv_potency.jobguide.snapshot import update_job_guide

    shutil.copytree("data/jobs/dnc", tmp_path / "jobs/dnc")
    html = Path("tests/fixtures/jobguide/dnc_full_7_56.html").read_text()
    changed = html.replace("Increases critical hit rate and direct hit rate by 20%.",
                           "Increases critical hit rate and direct hit rate by 21%.")
    assert changed != html
    update_job_guide(job="dancer", patch="7.56", output_root=tmp_path,
                     transport=httpx.MockTransport(lambda _: httpx.Response(200, text=changed)))
    document = json.loads(Path("data/raid_effects/7.4.json").read_text())
    old = resolve_effects(document, tmp_path, "7.55")
    new = resolve_effects(document, tmp_path, "7.56")
    assert [r["bonus"] for r in old if r["action"] == "Devilment"] == [.20, .20]
    assert [r["bonus"] for r in new if r["action"] == "Devilment"] == [.21, .21]
