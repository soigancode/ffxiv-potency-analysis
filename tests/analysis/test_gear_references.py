"""Check job reference stats against the supplied races and planner exports."""

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "job,set_name,filename",
    [
        ("dnc", "Savage Weapon BiS", "7.4_savage.json"),
        ("brd", "i790 7.4 Best In Slot", "7.4_savage.json"),
        ("mch", "7.4 BIS", "7.4_savage.json"),
        ("dnc", "Relic Weapon BiS", "7.55_relic.json"),
        ("brd", "i790 7.55 Best In Slot w/Relic bow", "7.55_relic.json"),
        ("mch", "BiS incl. Relic", "7.55_relic.json"),
        ("war", "2.5 Savage Weapon", "7.4_savage.json"),
        ("war", "2.5 Relic Weapon", "7.55_relic.json"),
    ],
)
def test_bis_matches_verified_planner_stats(job, set_name, filename):
    race = "Xaela" if job == "war" else "Seekers of the Sun"
    suffix = "xaela" if job == "war" else "seekers"
    export = json.loads(Path(f"tests/fixtures/gear/{job}_bis_{suffix}.json").read_text())
    assert export["race"] == race
    assert export["partyBonus"] == (5 if job == "war" else 0)
    selected = next(s for s in export["sets"] if s["name"] == set_name)
    stats = selected["computedStats"]
    gear = json.loads((Path("data/jobs") / job / "gear_sets" / filename).read_text())
    for our_name, planner_name in [
        ("party_strength", "strength") if job == "war" else ("solo_dexterity", "dexterity"),
        ("critical_hit", "crit"),
        ("direct_hit", "dhit"),
        ("determination", "determination"),
        ("skill_speed", "skillspeed"),
        ("weapon_damage", "wdPhys"),
        ("weapon_delay_seconds", "weaponDelay"),
    ]:
        assert gear[our_name] == stats[planner_name]
    main_stat = "strength" if job == "war" else "dexterity"
    assert gear[f"party_{main_stat}"] == gear[f"solo_{main_stat}"] * 105 // 100
    assert race in gear["source"]["race_assumption"]
    assert gear["source"]["set"] == set_name
    assert selected["food"] == 49240
    assert gear["source"]["url"] == f"https://xivgear.app/?page=bis%7C{job}%7Ccurrent"
    if filename == "7.55_relic.json":
        relic = {
            "crit": 447,
            "dhit": 0 if job == "war" else 108,
            "determination": 447,
            "skillspeed": 0,
        }
        if job == "war":
            relic["tenacity"] = 108
        assert selected["items"]["Weapon"]["relicStats"] == relic
    if job == "war":
        assert gear["tenacity"] == stats["tenacity"]
