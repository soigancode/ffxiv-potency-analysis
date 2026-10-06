"""Encounter locks restrict actions without pausing cooldown recovery."""

import pytest

from ffxiv_potency.analysis.availability import action_lock_windows, available_windows
from ffxiv_potency.analysis.execution import charge_maximum, summarize_execution
from ffxiv_potency.analysis.targetability import TargetableTime


def lock(time, kind, target=1, duration=None):
    event = {"timestamp": time, "type": kind, "targetID": target, "abilityGameID": 1000774}
    if duration is not None:
        event["duration"] = duration
    return event


@pytest.mark.parametrize("events,auras,expected", [
    ([lock(40000, "applydebuff"), lock(110000, "removedebuff")], [], ((40000, 110000),)),
    ([lock(10000, "removedebuff")], [], ((0, 10000),)),
    ([], [{"sourceID": 1, "auras": [{"ability": 1000774}]}], ((0, 180000),)),
    ([lock(40000, "applydebuff", duration=10000)], [], ((40000, 50000),)),
    ([lock(40000, "applydebuff"), lock(45000, "refreshdebuff"),
      lock(110000, "removedebuff")], [], ((40000, 110000),)),
    ([lock(-5000, "applydebuff"), lock(10000, "removedebuff")], [], ((0, 10000),)),
    ([lock(40000, "applydebuff", target=2)], [], ()),
    ([{"timestamp": 40000, "type": "applydebuff", "targetID": 1,
       "abilityGameID": 1002911, "duration": 30000}], [], ()),
])
def test_only_recorded_action_locks_exclude_uses(events, auras, expected):
    assert action_lock_windows(events, auras, {}, 1, 0, 180000) == expected


def test_locks_clip_and_split_availability():
    assert available_windows(((-10, 100), (150, 250)), ((50, 175),), 0, 200) == (
        (0, 50), (175, 200))


def test_long_and_short_cooldowns_recover_during_downtime_and_cap_charges():
    windows = ((0, 30000), (120000, 180000))
    assert charge_maximum(0, 180000, 120000, 1, [], windows) == 2
    assert charge_maximum(0, 180000, 30000, 1, [], windows) == 3
    assert charge_maximum(0, 180000, 30000, 2, [], windows) == 5
    free = available_windows(((0, 180000),), ((45000, 115000),), 0, 180000)
    assert charge_maximum(0, 180000, 30000, 1, [], free) == 5


@pytest.mark.parametrize("job,buff,attack", [
    ("paladin", "Fight or Flight", "Imperator"),
    ("warrior", "Inner Release", "Upheaval"),
    ("bard", "Raging Strikes", None),
    ("machinist", "Reassemble", "Wildfire"),
    ("dancer", "Technical Step", None),
])
def test_self_actions_can_be_used_before_target_returns_but_not_during_lock(job, buff, attack):
    actions = {buff: {"recast_seconds": 30, "potency": None}}
    if attack:
        actions[attack] = {"recast_seconds": 30, "potency": {"base": 100}}
    result = summarize_execution(job, [], [], [],
        [lock(45000, "applydebuff"), lock(115000, "removedebuff")],
        [{"timestamp": 5000, "type": "death", "targetID": 1}], [], {}, actions, {},
        1, 0, 180000, TargetableTime(90, "timeline", ((0, 30000), (120000, 180000))), {})
    rows = {row.name: row for row in result.cooldowns}
    assert rows[buff].possible == 5
    assert rows[buff].basis == "action availability"
    if attack:
        label = "Upheaval/Orogeny" if attack == "Upheaval" else attack
        assert rows[label].possible == 3


@pytest.mark.parametrize("targetable,expected", [
    (TargetableTime(0, "timeline"), 0),
    (TargetableTime(None, "unknown"), None),
])
def test_missing_target_timeline_does_not_invent_damaging_opportunities(targetable, expected):
    result = summarize_execution("paladin", [], [], [], [], [], [], {},
        {"Imperator": {"recast_seconds": 60, "potency": {"base": 580}},
         "Fight or Flight": {"recast_seconds": 60, "potency": None}}, {},
        1, 0, 180000, targetable, {})
    rows = {row.name: row for row in result.cooldowns}
    assert rows["Imperator"].possible == expected
    assert rows["Fight or Flight"].possible == 3
