"""Check job reference stats against the verified Seekers planner export."""

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "job,set_name,filename",
    [
        ("dnc", "Savage Weapon BiS", "7.4_savage.json"),
        ("brd", "i790 7.4 Best In Slot", "7.4_savage.json"),
        ("mch", "2.50 - Savage", "7.4_savage.json"),
        ("dnc", "Relic Weapon BiS", "7.55_relic.json"),
        ("brd", "i790 7.55 Best In Slot w/Relic bow", "7.55_relic.json"),
        ("mch", "2.50 - Relic", "7.55_relic.json"),
    ],
)
def test_bis_matches_verified_planner_stats(job, set_name, filename):
    export = json.loads(Path(f"tests/fixtures/gear/{job}_bis_seekers.json").read_text())
    assert export["race"] == "Seekers of the Sun"
    assert export["partyBonus"] == 0
    selected = next(s for s in export["sets"] if s["name"] == set_name)
    stats = selected["computedStats"]
    gear = json.loads((Path("data/jobs") / job / "gear_sets" / filename).read_text())
    for our_name, planner_name in [
        ("solo_dexterity", "dexterity"),
        ("critical_hit", "crit"),
        ("direct_hit", "dhit"),
        ("determination", "determination"),
        ("skill_speed", "skillspeed"),
        ("weapon_damage", "wdPhys"),
        ("weapon_delay_seconds", "weaponDelay"),
    ]:
        assert gear[our_name] == stats[planner_name]
    assert gear["party_dexterity"] == stats["dexterity"] * 105 // 100
    assert "Seekers of the Sun" in gear["source"]["race_assumption"]
    assert selected["food"] == 49240
    assert gear["source"]["url"] == f"https://xivgear.app/?page=bis%7C{job}%7Ccurrent"
    if filename == "7.55_relic.json":
        assert selected["items"]["Weapon"]["relicStats"] == {
            "crit": 447,
            "dhit": 108,
            "determination": 447,
            "skillspeed": 0,
        }
