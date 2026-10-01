"""The supported BiS stats include the shared HQ meal's capped bonuses."""

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.mark.parametrize("job", ["bard", "machinist"])
@pytest.mark.parametrize("set_name", ["7.4_savage", "7.55_relic"])
def test_bis_food_reference_and_unfed_stats(job: str, set_name: str) -> None:
    gear = json.loads((DATA / "jobs" / {"bard": "brd", "machinist": "mch"}[job] / "gear_sets" / f"{set_name}.json").read_text())
    profile = json.loads((DATA / "jobs" / {"bard": "brd", "machinist": "mch"}[job] / "gear_sets/7.55_relic.json").read_text())
    food = json.loads((DATA / "consumables" / gear["food"]).read_text())

    assert gear["food"] == profile["food"]
    assert (food["name"], food["quality"]) == ("Caramel Popcorn", "HQ")
    assert food["buff_id"] == 1000048
    for stat, cap in (("critical_hit", 91), ("determination", 151)):
        bonus = food["bonuses"][stat]
        fed_value = gear[stat]
        unfed_value = fed_value - cap
        assert bonus == {"percent": 10, "cap": cap}
        assert min(unfed_value // 10, cap) == cap
        if set_name == "7.55_relic":
            assert profile[stat] == fed_value


@pytest.mark.parametrize("job", ["bard", "machinist"])
def test_hq_potion_shared_by_supported_jobs(job: str) -> None:
    profile = json.loads((DATA / "jobs" / {"bard": "brd", "machinist": "mch"}[job] / "gear_sets/7.55_relic.json").read_text())
    potion = json.loads((DATA / "consumables" / profile["potion"]).read_text())

    assert potion["quality"] == "HQ"
    assert potion["name"] == "Grade 4 Gemdraught of Dexterity"
    assert potion["bonuses"]["dexterity"] == {"percent": 10, "cap": 541}
    before = profile["party_dexterity"]
    assert min(before // 10, 541) == 541
