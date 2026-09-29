"""Paladin damage events establish the penalty for both M12S phases."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis.penalties import load_damage_penalties


@pytest.mark.parametrize(
    ("prefix", "encounter", "affected_hits", "start_seconds"),
    [
        ("vKDTWyjdrg2m7Phz/fight-4/source-9/", 104, 52, 157.157),
        ("9rDhyHg8mdqzZAT6/fight-24/source-1454/", 105, 35, 233.639),
    ],
)
def test_lindwurm_damage_down_is_half_damage(
    tmp_path: Path, extract_fight, prefix: str, encounter: int,
    affected_hits: int, start_seconds: float,
) -> None:
    extract_fight("pld_lindwurm_damage_down.zip", prefix)
    fight = json.loads((tmp_path / "fight.json").read_text())
    master = json.loads((tmp_path / "master-data.json").read_text())
    damage = json.loads((tmp_path / "damage-events.json").read_text())
    debuffs = json.loads((tmp_path / "debuff-events.json").read_text())

    assert fight["encounterID"] == encounter
    assert load_damage_penalties(encounter)[1002911] == ("Damage Down", 0.5)
    source_id = int(prefix.rstrip("/").rsplit("source-", 1)[1])
    assert next(actor for actor in master["actors"] if actor["id"] == source_id)["subType"] == (
        "Paladin"
    )
    applications = [event for event in debuffs if event.get("targetID") == source_id
                    and event.get("type") == "applydebuff"
                    and event.get("abilityGameID") == 1002911]
    assert (applications[0]["timestamp"] - fight["startTime"]) / 1000 == pytest.approx(
        start_seconds
    )

    normal = [event for event in damage if event.get("type") == "damage"
              and event.get("amount", 0) > 0 and not event.get("buffs")]
    penalized = [event for event in damage if event.get("type") == "damage"
                 and event.get("amount", 0) > 0 and event.get("buffs") == "1002911."]
    assert normal and penalized
    assert {event.get("multiplier") for event in normal} == {1}
    assert {event.get("multiplier") for event in penalized} == {0.5}
    assert sum("1002911" in str(event.get("buffs", "")).split(".") for event in damage
               if event.get("type") == "damage" and event.get("amount", 0) > 0) == affected_hits
