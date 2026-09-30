"""Real dungeon pull with ten multi-target Bioblaster applications."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.dots import DotRules, reconstruct_dot_ticks
from ffxiv_potency.analysis.profiles import _load_combat_profile

ARCHIVE = "mch_bioblaster_dungeon.zip"
PREFIX = "6WNQp2yC3Lj7KYvJ/fight-4/source-42/"
ACTIONS = Path(__file__).parents[2] / "data/machinist/7.55/actions.json"


def test_bioblaster_applications_ticks_and_snapshots(tmp_path: Path, extract_fight) -> None:
    extract_fight(ARCHIVE, PREFIX)
    result = analyze_saved_fight(tmp_path, ACTIONS)
    action = next(row for row in result.actions if row.name == "Bioblaster")

    assert result.encounter_id == 4551
    assert result.fight_name == "the Clyteum"
    assert result.unmatched == ()
    assert (action.uses, action.hits) == (10, 237)
    assert not any(name == "Bioblaster" for name, _ in result.ghosted)

    master = json.loads((tmp_path / "master-data.json").read_text())
    names = {ability["gameID"]: ability["name"] for ability in master["abilities"]}
    damage = json.loads((tmp_path / "damage-events.json").read_text())
    hits = [event for event in damage if event.get("type") == "damage"
            and names.get(event.get("abilityGameID")) == "Bioblaster"]
    applications = [event for event in hits if not event.get("tick")]
    ticks = [event for event in hits if event.get("tick")]
    assert (len(applications), len(ticks)) == (47, 190)
    assert {event.get("targetInstance") for event in applications
            if event.get("packetID") == 35358 and event.get("targetID") == 46} == {1, 2}

    matched = reconstruct_dot_ticks(
        damage, names, 42, DotRules(frozenset({"Bioblaster"}), duration_ms=15_000),
    )
    assert len(matched) == 190
    assert all(tick.matched for tick in matched)
    assert sum("1000049" in tick.snapshot_buffs.split(".") for tick in matched) == 13
    assert all(tick.snapshot_buffs == tick.tick_buffs for tick in matched)

    # 237 hits at 50 potency, two clipped overkill hits, and 16 potted hits
    # (three applications plus thirteen ticks) from the first application.
    profile = _load_combat_profile("machinist", json.loads(ACTIONS.read_text()))
    expected = (
        237 * 50 - 50 * (1297 / 8295 + 4078 / 7572)
        + 16 * 50 * (profile.player_potion_multiplier - 1)
    )
    assert action.potency_min == pytest.approx(expected)


def test_hypercharge_does_not_increase_aoe_weaponskills(tmp_path: Path, extract_fight) -> None:
    extract_fight(ARCHIVE, PREFIX)
    result = analyze_saved_fight(tmp_path, ACTIONS)
    actions = {action.name: action for action in result.actions}

    assert actions["Scattergun"].potency_min == pytest.approx(7474.010152284264)
    assert actions["Auto Crossbow"].potency_min == pytest.approx(21540.12949622104)
    assert actions["Blazing Shot"].potency_min == pytest.approx(11596.185300309224)
