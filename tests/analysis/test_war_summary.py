"""Visible Warrior ready effects and timestamped ranged GCD diagnostics."""

from ffxiv_potency.analysis.targetability import TargetableTime, targetable_intervals
from ffxiv_potency.analysis.war.summary import summarize_war


def test_ready_losses_charges_and_tomahawk_neighbors():
    names = {
        1: "Heavy Swing",
        2: "Tomahawk",
        3: "Maim",
        4: "Fell Cleave",
        5: "Primal Rend",
        6: "Inner Release",
    }
    actions = {name: {"type": "Weaponskill"} for name in names.values()}
    actions["Inner Release"]["type"] = "Ability"
    casts = [
        {"timestamp": time, "type": "cast", "sourceID": 1, "abilityGameID": ability}
        for time, ability in [
            (0, 1),
            (2500, 2),
            (5000, 3),
            (6000, 6),
            (6500, 4),
            (15000, 5),
            (20000, 2),
            (21000, 6),
            (29870, 2),
            (33350, 1),
        ]
    ]

    def buff(time, kind, status, duration=5000):
        return {
            "timestamp": time,
            "type": kind,
            "sourceID": 1,
            "targetID": 1,
            "abilityGameID": status,
            "duration": duration,
        }

    buffs = [
        buff(6000, "applybuff", 1001177),
        buff(11000, "removebuff", 1001177),
        buff(6000, "applybuff", 1002624),
        buff(11000, "removebuff", 1002624),
        buff(12000, "applybuff", 1002624),
        buff(15000, "removebuff", 1002624),
        buff(1000, "applybuff", 1001897),
        buff(2000, "refreshbuff", 1001897),
        buff(7000, "removebuff", 1001897),
    ]
    result = summarize_war(
        casts,
        buffs,
        [],
        names,
        actions,
        1,
        0,
        40000,
        [(1000, "Heavy Swing", 240, 1), (5000, "Maim", 374, 1.1)],
        TargetableTime(None, "unavailable"),
        {},
    )
    assert result.tempest_lost_potency == 0
    assert result.guaranteed_spenders == 1
    assert result.unused_expired_charges == 2
    rend, _, _, chaos = result.ready
    assert (rend.grants, rend.uses, rend.expired, rend.remaining) == (2, 1, 1, 0)
    assert (chaos.overwritten, chaos.expired) == (1, 1)
    use = result.tomahawks[0]
    assert (use.seconds, use.previous, use.previous_gap, use.following, use.following_gap) == (
        2.5,
        "Heavy Swing",
        2.5,
        "Maim",
        2.5,
    )
    assert len(result.tomahawks) == 2
    chain = result.tomahawks[1]
    assert (chain.seconds, chain.previous, chain.previous_gap) == (20, "Primal Rend", 5)
    assert chain.gaps == (9.87,)
    assert (chain.following, chain.following_gap) == ("Heavy Swing", 3.48)


def test_targetable_union_does_not_double_count_two_bosses_or_transitions():
    damage = [
        {"type": "damage", "timestamp": 0, "targetID": 10, "amount": 100},
        {"type": "damage", "timestamp": 20000, "targetID": 11, "amount": 100},
        {"type": "damage", "timestamp": 20000, "targetID": 12, "amount": 100},
    ]
    updates = [
        {"type": "targetabilityupdate", "timestamp": time, "sourceID": target, "targetable": state}
        for time, target, state in [
            (10000, 10, 0),
            (20000, 11, 1),
            (20000, 12, 1),
            (30000, 11, 0),
            (30000, 12, 0),
        ]
    ]
    windows = {1002677: ((5000, 25000, 1.1),)}
    actors = {id_: {"type": "NPC", "subType": "Boss"} for id_ in (10, 11, 12)}
    intervals = targetable_intervals(updates, damage, [], actors, 0, 40000)
    assert intervals == ((0, 10000), (20000, 30000))
    covered = sum(max(0, min(b, d) - max(a, c)) for a, b in intervals for c, d, _ in windows[1002677])
    assert covered == 10000


def test_tempest_setup_excludes_only_required_combos_and_confirmed_downtime_expiry():
    from ffxiv_potency.analysis.war.summary import _tempest_setup_windows

    names = {1: "Heavy Swing", 2: "Maim", 3: "Storm's Eye", 4: "Fell Cleave", 5: "Infuriate"}
    actions = {name: {"type": "Weaponskill"} for name in names.values()}
    actions["Infuriate"]["type"] = "Ability"
    casts = [{"timestamp": time, "abilityGameID": ability} for time, ability in
             [(0, 1), (1000, 5), (2500, 2), (5000, 3),
              (40000, 1), (42500, 2), (45000, 3), (47500, 4)]]
    buffs = [{"timestamp": 5000, "abilityGameID": 1002677, "type": "applybuff", "duration": 30000}]
    windows = {1002677: ((5000, 35000, 1.1), (45000, 60000, 1.1))}
    targetable = TargetableTime(40, "timeline", ((0, 20000), (40000, 60000)))
    assert _tempest_setup_windows(casts, buffs, names, actions, set(), 0, 60000, targetable, windows) == [
        (0, 5000), (40000, 45000),
    ]
    # Continuous targetability cannot excuse the reopener. Unknown duration cannot either.
    continuous = TargetableTime(60, "timeline", ((0, 60000),))
    assert _tempest_setup_windows(casts, buffs, names, actions, set(), 0, 60000, continuous, windows) == [(0, 5000)]
    buffs[0].pop("duration")
    assert _tempest_setup_windows(casts, buffs, names, actions, set(), 0, 60000, targetable, windows) == [(0, 5000)]
    # A spender before or during the opener does not turn setup into an issue.
    casts[2]["abilityGameID"] = 4
    assert _tempest_setup_windows(casts, buffs, names, actions, set(), 0, 60000, continuous, windows) == [(0, 5000)]
    assert _tempest_setup_windows(casts, buffs, names, actions, {1002677}, 0, 60000, continuous, windows) == []
