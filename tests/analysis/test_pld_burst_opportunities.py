"""PLD package opportunities distinguish casts, hits, grants and uncertainty."""

import json
from pathlib import Path

from ffxiv_potency.analysis.burst_opportunities import BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.pld.buffs import FIGHT_OR_FLIGHT
from ffxiv_potency.analysis.pld.burst_opportunities import (
    BURST_ACTIONS,
    summarize_burst_opportunities,
)
from ffxiv_potency.analysis.targetability import TargetableTime

ACTIONS = {a["name"]: a for a in json.loads(
    Path("data/jobs/pld/7.4/actions.json").read_text())["actions"]}
NAMES = {i: name for i, name in enumerate(BURST_ACTIONS, 1)}
IDS = {name: i for i, name in NAMES.items()}


def cast(time, name):
    return {"timestamp": time, "type": "cast", "sourceID": 1,
            "abilityGameID": IDS[name], "packetID": time}


def grant(time, status, duration=30000):
    return {"timestamp": time, "type": "applybuff", "sourceID": 1, "targetID": 1,
            "abilityGameID": status, "duration": duration}


def summary(casts=(), buffs=(), life=(), damage=(), targetable=None, end=20000, potency=(),
            fight_end=60000):
    return summarize_burst_opportunities(casts, buffs, life, NAMES, ACTIONS, 1, 0, fight_end,
        {FIGHT_OR_FLIGHT: ((0, end, 1.25),)},
        targetable or TargetableTime(fight_end / 1000, "test", ((0, fight_end),)), damage, potency)[0]


def test_recorded_grant_unlocks_combo_and_honor_without_hardcoded_counts():
    w = summary(buffs=(grant(0, 1003019), grant(0, 1001368), grant(0, 1003847)))
    rows = {a.name: a for a in w.actions}
    for name in ("Goring Blade", "Confiteor", "Blade of Faith", "Blade of Truth",
                 "Blade of Valor", "Blade of Honor"):
        assert (rows[name].casts, rows[name].expected) == (0, 1)
    assert rows["Imperator"].expected is None
    assert _decode(_encode(w), BurstWindow) == w


def test_completed_cast_with_no_hit_and_multi_target_hit_counts_are_separate():
    casts = [cast(1000, "Confiteor"), cast(3500, "Blade of Faith")]
    damage = [{**casts[1], "type": "damage", "amount": 100, "targetID": target}
              for target in (2, 3)]
    w = summary(casts=(*casts, casts[1]), damage=damage,
                buffs=(grant(0, 1003019),), potency=((1000, "Confiteor", 0, True),
                                                  (3500, "Blade of Faith", 364, True)))
    rows = {a.name: a for a in w.actions}
    assert (rows["Confiteor"].casts, rows["Confiteor"].hits) == (1, 0)
    assert (rows["Blade of Faith"].casts, rows["Blade of Faith"].hits) == (1, 2)
    assert w.landed_potency == 455


def test_grants_cannot_survive_death_or_be_spent_twice():
    w = summary(buffs=(grant(-1000, 1003019),),
                casts=(cast(-500, "Confiteor"),))
    assert next(a for a in w.actions if a.name == "Confiteor").expected is None
    w = summary(buffs=(grant(0, 1003019),),
                life=({"timestamp": 1000, "type": "death", "targetID": 1},))
    rows = {a.name: a for a in w.actions}
    assert rows["Confiteor"].expected == 1
    assert rows["Blade of Faith"].expected == 0


def test_truncated_window_and_missing_targetability_do_not_invent_full_package():
    w = summary(buffs=(grant(0, 1003019), grant(0, 1001368)), end=3000)
    rows = {a.name: a for a in w.actions}
    assert rows["Confiteor"].expected == rows["Blade of Faith"].expected == 1
    assert rows["Blade of Truth"].expected == rows["Blade of Valor"].expected == 0
    w = summary(buffs=(grant(0, 1003019),), targetable=TargetableTime(None, "unknown"))
    assert all(a.expected is None for a in w.actions)


def test_outside_cleave_is_preserved_without_potential_loss_finding():
    w = summary(casts=(cast(-30000, "Expiacion"), cast(21000, "Expiacion")))
    assert next(a for a in w.actions if a.name == "Expiacion").expected == 0


def test_outside_multi_target_follow_up_does_not_become_a_missing_burst_action():
    outside = cast(21000, "Confiteor")
    damage = [{**outside, "type": "damage", "amount": 100, "targetID": target}
              for target in (2, 3)]
    w = summary(casts=(outside,), buffs=(grant(0, 1003019),), damage=damage)
    row = next(a for a in w.actions if a.name == "Confiteor")
    assert row.casts == 0
    assert row.expected is None
    assert row.notes == ("outside multi-target use retained",)
    assert all(a.expected is None for a in w.actions
               if a.name in {"Blade of Faith", "Blade of Truth", "Blade of Valor", "Blade of Honor"})
