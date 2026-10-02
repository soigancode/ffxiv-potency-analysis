"""A phase closure must not become a target-death issue marker."""

from ffxiv_potency.analysis.phase_locks import phase_lock_windows


def test_delayed_phase_closure_without_dot_ticks_and_real_add_death():
    overkills = [{"timestamp": 10000, "targetID": 1, "overkill": 20}]
    casts = [{"timestamp": t, "targetID": 1} for t in (12500, 15000)]
    updates = [{"timestamp": 16000, "sourceID": 1, "targetable": 0}]
    boss = {1: {"subType": "Boss"}}
    windows = phase_lock_windows(overkills, casts, [], boss, updates, 60000)
    assert windows == {1: [(7500, 16000)]}
    assert phase_lock_windows(overkills, casts, [], {1: {"subType": "NPC"}}, updates, 60000) == {}
    # A final kill and a target still taking normal damage do not prove a phase lock.
    assert phase_lock_windows(overkills, casts, [], boss, updates, 17000) == {}
    damage = [{"type": "damage", "timestamp": 13000, "targetID": 1, "amount": 100}]
    assert phase_lock_windows(overkills, casts, damage, boss, updates, 60000) == {}


def test_repeated_overkill_includes_already_resolving_attacks():
    hits = [{"timestamp": t, "targetID": 1, "overkill": 50} for t in (10000, 13000, 16000)]
    assert phase_lock_windows(hits, [], [], {1: {"subType": "Boss"}}, [], 60000) == {
        1: [(7500, 20000)]
    }


def test_lock_continues_until_disappearance_when_ticks_stop_early():
    hits = [{"timestamp": t, "targetID": 1, "overkill": 50} for t in (10000, 13000)]
    updates = [{"timestamp": 27000, "sourceID": 1, "targetable": 0}]
    boss = {1: {"subType": "Boss"}}
    assert phase_lock_windows(hits, [], [], boss, updates, 60000) == {1: [(7500, 27000)]}
    damage = [{"timestamp": 20000, "type": "damage", "targetID": 1, "amount": 100}]
    assert phase_lock_windows(hits, [], damage, boss, updates, 60000) == {1: [(7500, 17000)]}


def test_dancing_mad_paired_closure_includes_later_chaos_cast():
    bosses = {
        1: {"gameID": 19509, "subType": "Boss"},
        2: {"gameID": 19508, "subType": "Boss"},
    }
    hits = [
        {"timestamp": 10000, "targetID": 1, "overkill": 20},
        {"timestamp": 16000, "targetID": 2, "overkill": 20},
    ]
    updates = [
        {"timestamp": 10000, "sourceID": 1, "targetable": 0},
        {"timestamp": 16000, "sourceID": 2, "targetable": 0},
    ]
    # Positive damage on the second boss does not reopen the paired phase.
    damage = [{"timestamp": 14000, "targetID": 2, "type": "damage", "amount": 100}]
    assert phase_lock_windows(hits, [], damage, bosses, updates, 60000, 1085) == {
        1: [(7500, 10000)], 2: [(7500, 16000)]
    }
    assert phase_lock_windows(hits, [], damage, bosses, updates, 60000, 104) == {}
    assert phase_lock_windows(hits[:1], [], damage, bosses, updates, 60000, 1085) == {}
    assert phase_lock_windows(hits, [], damage, bosses, updates, 17000, 1085) == {}
