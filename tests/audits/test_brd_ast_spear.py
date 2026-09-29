"""Real BRD hits carrying Astrologian's The Spear damage buff."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis.brd.variable_potency import _brd_damage_estimates
from ffxiv_potency.analysis.profiles import _load_combat_profile

ARCHIVE = "brd_ast_spear.zip"
SPEAR = "1003889"
ACTIONS = Path(__file__).parents[2] / "data/bard/7.55/actions.json"


def _events(directory: Path):
    master = json.loads((directory / "master-data.json").read_text())
    names = {ability["gameID"]: ability["name"] for ability in master["abilities"]}
    damage = json.loads((directory / "damage-events.json").read_text())
    landed = [event for event in damage if event.get("type") == "damage"
              and event.get("hitType") != 10 and event.get("amount") != 0]
    return names, damage, landed


def test_spear_alone_appears_in_fflogs_damage_multiplier(tmp_path: Path, extract_fight) -> None:
    extract_fight(ARCHIVE, "YMQxFTN3HGrWJjzB/fight-2/source-6/")
    _, _, landed = _events(tmp_path)
    with_spear = [event for event in landed if event.get("buffs") == "1003889.1002218."]
    without_spear = [event for event in landed if event.get("buffs") == "1002218."]

    assert len(with_spear) == 43
    assert without_spear
    assert {event["multiplier"] for event in with_spear} == {1.06}
    assert {event["multiplier"] for event in without_spear} == {1}


def test_spear_is_removed_before_pitch_perfect_classification(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight(ARCHIVE, "jr9NMvCXhRGcDzdy/fight-2/source-330/")
    names, damage, landed = _events(tmp_path)
    casts = json.loads((tmp_path / "cast-events.json").read_text())
    fight = json.loads((tmp_path / "fight.json").read_text())
    profile = _load_combat_profile("bard", json.loads(ACTIONS.read_text()))
    inferred, _ = _brd_damage_estimates(
        landed, casts, damage, names, profile.critical_damage_multiplier,
        fight_start=fight["startTime"], potion_multiplier=profile.player_potion_multiplier,
        combat_profile=profile,
    )

    hits = [event for event in landed if names.get(event.get("abilityGameID")) == "Pitch Perfect"
            and SPEAR in event.get("buffs", "").split(".")]
    assert len(hits) == 2
    assert {event["multiplier"] for event in hits} == {1.36}
    assert [inferred[id(event)] for event in hits] == [(360, False, 0.0)] * 2

    for event in hits:
        normalized = event["amount"] / event["multiplier"]
        if event.get("hitType") == 2:
            normalized /= profile.critical_damage_multiplier
        if event.get("directHit"):
            normalized /= 1.25
        assert normalized / 360 == pytest.approx(100, abs=6.5)
