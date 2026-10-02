"""Execution diagnostics must follow actual events and explicit evidence."""

from ffxiv_potency.analysis.execution import (
    charge_maximum,
    coverage,
    ready_summary,
    summarize_execution,
)
from ffxiv_potency.analysis.targetability import TargetableTime


def test_charge_simulation_boundaries_reductions_and_downtime():
    assert charge_maximum(0, 60000, 30000, 3, [], ((0, 60000),)) == 4
    assert charge_maximum(0, 60001, 30000, 3, [], ((0, 60001),)) == 5
    assert charge_maximum(0, 60000, 30000, 3, [(10000, 15000)], ((0, 60000),)) == 5
    # Reductions during a long gap cannot stock more than three charges.
    assert (
        charge_maximum(
            0, 120000, 30000, 3, [(20000, 15000), (40000, 15000)], ((0, 10000), (110000, 120000))
        )
        == 6
    )
    assert charge_maximum(0, 60000, 30000, 3, [], ()) == 0


def test_coverage_unions_overlapping_windows_and_preserves_gaps():
    value = coverage("buff", [(5000, 20000), (15000, 25000)], ((0, 10000), (15000, 30000)), 0)
    assert value.targetable_seconds == 25
    assert value.covered_seconds == 15
    assert value.gaps == ((0, 5), (25, 30))
    assert value.avoidable_gaps == ((25, 30),)


def test_ready_expiry_death_and_remaining_are_not_interchangeable():
    names = {1: "Spend"}
    buffs = [{"timestamp": 0, "type": "applybuff", "abilityGameID": 2, "duration": 10000}]
    result = ready_summary(("Ready", names), 2, {"Spend"}, [], buffs, set(), [], 1, 0, 5000, 10000)
    assert (result.remaining, result.expired) == (1, 0)
    result = ready_summary(("Ready", names), 2, {"Spend"}, [], buffs, set(), [], 1, 0, 15000, 10000)
    assert (result.remaining, result.expired) == (0, 1)
    death = [{"timestamp": 5000, "type": "death", "targetID": 1}]
    result = ready_summary(
        ("Ready", names), 2, {"Spend"}, [], buffs, set(), death, 1, 0, 15000, 10000
    )
    assert (result.death_lost, result.expired) == (1, 0)
    assert result.losses == ((5, "death"),)


def test_repertoire_warning_requires_resolved_empyreal_and_no_later_pitch_perfect():
    names = {
        1: "The Wanderer's Minuet",
        2: "Empyreal Arrow",
        3: "Pitch Perfect",
        4: "Mage's Ballad",
    }
    casts = [
        {"type": "cast", "sourceID": 7, "timestamp": t, "abilityGameID": a, "packetID": t}
        for t, a in [(0, 1), (20000, 2), (40000, 4)]
    ]
    damage = [
        {
            "type": "calculateddamage",
            "sourceID": 7,
            "timestamp": 20000,
            "abilityGameID": 2,
            "packetID": 20000,
            "amount": 100,
        }
    ]

    def run(casts, damage, life=()):
        return summarize_execution(
            "bard",
            casts,
            damage,
            [],
            [],
            life,
            [],
            names,
            {},
            {},
            7,
            0,
            60000,
            TargetableTime(60, "timeline", ((0, 60000),)),
            {},
        )

    assert run(casts, damage).repertoire_losses == (40,)
    assert run(casts, []).repertoire_losses == ()
    pp = {"type": "cast", "sourceID": 7, "timestamp": 39999, "abilityGameID": 3}
    assert run([*casts, pp], damage).repertoire_losses == ()
    assert (
        run(casts, damage, [{"type": "death", "targetID": 7, "timestamp": 40000}]).repertoire_losses
        == ()
    )


def test_consumer_after_expiry_cannot_spend_an_expired_ready_effect():
    casts = [{"type": "cast", "sourceID": 1, "timestamp": 12000, "abilityGameID": 1}]
    buffs = [{"timestamp": 0, "type": "applybuff", "abilityGameID": 2, "duration": 10000}]
    value = ready_summary(
        ("Ready", {1: "Spend"}), 2, {"Spend"}, casts, buffs, set(), [], 1, 0, 15000, 10000
    )
    assert (value.expired, value.uses, value.remaining) == (1, 0, 0)
    assert value.losses == ((10, "expired"),)


def test_refresh_from_same_action_packet_is_one_ready_grant():
    buffs = [
        {
            "timestamp": 0,
            "type": "applybuff",
            "abilityGameID": 2,
            "packetID": 10,
            "duration": 30000,
        },
        {
            "timestamp": 2000,
            "type": "refreshbuff",
            "abilityGameID": 2,
            "packetID": 10,
            "duration": 30000,
        },
    ]
    casts = [{"timestamp": 5000, "type": "cast", "abilityGameID": 1}]
    value = ready_summary(
        ("Ready", {1: "Spend"}), 2, {"Spend"}, casts, buffs, set(), [], 1, 0, 40000, 30000
    )
    assert (value.grants, value.uses, value.overwritten, value.expired) == (1, 1, 0, 0)


def test_hypercharge_reports_complete_and_truncated_windows():
    names = {1: "Blazing Shot"}
    casts = [
        {"timestamp": t, "type": "cast", "abilityGameID": 1}
        for t in (1000, 2000, 3000, 4000, 5000, 11000, 12000)
    ]
    buffs = [
        {"timestamp": t, "type": "applybuff", "abilityGameID": 2, "duration": 10000}
        for t in (0, 10000)
    ]
    value = ready_summary(
        ("Hypercharge", names), 2, {"Blazing Shot"}, casts, buffs, set(), [], 1, 0, 13000, 10000, 5
    )
    assert [(w.start_seconds, w.uses, w.charges, w.end_reason) for w in value.windows] == [
        (0, 5, 5, "Complete"),
        (10, 2, 5, "Fight ended"),
    ]
    assert (value.grants, value.uses, value.remaining, value.expired) == (10, 7, 3, 0)
    expired = ready_summary(
        ("Hypercharge", names), 2, {"Blazing Shot"}, casts, buffs, set(), [], 1, 0, 25000, 10000, 5
    )
    assert expired.windows[-1].end_reason == "Expired"
    assert expired.expired == 3


def test_radiant_finale_display_follows_two_minute_cycle_without_changing_actions():
    actions = {"Radiant Finale": {"recast_seconds": 110, "description": []}}
    value = summarize_execution(
        "bard",
        [],
        [],
        [],
        [],
        [],
        [],
        {},
        actions,
        {},
        1,
        0,
        1111000,
        TargetableTime(1111, "timeline", ((0, 1111000),)),
        {},
    )
    finale = next(c for c in value.cooldowns if c.name == "Radiant Finale")
    assert finale.possible == 10
    assert actions["Radiant Finale"]["recast_seconds"] == 110


def test_bard_dot_coverage_follows_confirmed_delayed_refresh_chain():
    names = {1: "Caustic Bite", 2: "Stormbite", 3: "Iron Jaws"}

    def hit(time, ability, packet, tick=False, target=10):
        return {
            "type": "damage", "sourceID": 7, "targetID": target,
            "timestamp": time, "abilityGameID": ability, "packetID": packet,
            "amount": 100, "tick": tick,
        }

    damage = [hit(0, 1, 1), hit(0, 2, 2), hit(45500, 3, 3), hit(90000, 3, 4)]
    ticks = [
        hit(time, ability, packet, tick=True)
        for time, packet in [(46000, 3), (91000, 4)] for ability in (1, 2)
    ]

    def run(events):
        return summarize_execution(
            "bard", [], events, [], [], [], [], names, {}, {}, 7, 0, 120000,
            TargetableTime(120, "timeline", ((0, 120000),)), {},
        )

    result = run(list(reversed(damage + ticks)))
    dots = [c for c in result.coverage if c.name in {"Caustic Bite", "Stormbite"}]
    assert len(dots) == 2
    for dot in dots:
        assert (dot.applications, dot.refreshes) == (1, 2)
        assert dot.covered_seconds == 119.5
        assert dot.gaps == ((45, 45.5),)
    # Iron Jaws cannot revive expired DoTs without evidence of the new snapshot.
    for dot in run(damage).coverage:
        if dot.name in {"Caustic Bite", "Stormbite"}:
            assert dot.refreshes == 0
            assert dot.covered_seconds == 45
    # The other target has no DoTs to refresh.
    unrelated = [hit(30000, 3, 5, target=20)]
    assert run(damage + ticks + unrelated).coverage == result.coverage
