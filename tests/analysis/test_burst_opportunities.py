"""Burst bounds preserve grants, targetable time and later cooldown uses."""

from ffxiv_potency.analysis.burst_opportunities import (
    GrantedAction,
    cooldown_opportunities,
    granted_package,
)


def test_granted_package_chooses_whole_combo_by_reference_potency():
    actions = (
        GrantedAction("Starter", 0, 20000, 2500, 100),
        GrantedAction("Follow", 0, 20000, 2500, 1000, "Starter"),
        GrantedAction("Other", 0, 20000, 2500, 700),
    )
    # Two GCD slots: choosing the largest immediately available action first
    # would lose the more valuable starter/follow-up package.
    assert granted_package(actions, ((0, 5000),), 0, 5000) == ("Starter", "Follow")
    changed = (actions[0], actions[1], GrantedAction("Other", 0, 20000, 2500, 2000))
    assert set(granted_package(changed, ((0, 5000),), 0, 5000)) == {"Other", "Starter"}


def test_downtime_does_not_freeze_gcd_and_expired_grants_are_unavailable():
    actions = (
        GrantedAction("Starter", 0, 10000, 2500, 100),
        GrantedAction("Follow", 0, 10000, 2500, 1000, "Starter"),
        GrantedAction("Expired", 0, 2000, 2500, 2000),
    )
    assert granted_package(actions, ((3000, 4000), (8000, 9000)), 0, 10000) == (
        "Starter", "Follow",
    )
    assert granted_package(actions, (), 0, 10000) == ()


def test_cooldown_opportunity_cannot_cost_next_recorded_use():
    assert cooldown_opportunities((-30000, 21000), 30000, 1, 0, 20000,
                                  ((0, 20000),)) == 0
    assert cooldown_opportunities((-30000, 60000), 30000, 1, 0, 20000,
                                  ((0, 20000),)) == 1


def test_charge_recovery_continues_through_downtime_without_inventing_opening_charges():
    assert cooldown_opportunities((), 30000, 2, 0, 20000, ((0, 20000),)) is None
    assert cooldown_opportunities((-90000,), 30000, 2, 0, 20000, ((10000, 20000),)) == 2
    assert cooldown_opportunities((-90000,), 30000, 2, 0, 20000, ()) == 0
    assert cooldown_opportunities((-1000,), 30000, 2, 0, 20000, ((0, 20000),)) == 0


def test_joint_package_accounts_for_earned_wrath_and_hit_delay():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (
        GrantedAction('FC1', 0, 15000, 2500, 580, impact_ms=626),
        GrantedAction('FC2', 0, 15000, 2500, 580, 'FC1', impact_ms=626),
        GrantedAction('FC3', 0, 15000, 2500, 580, 'FC2', impact_ms=626),
        GrantedAction('Rend', 0, 30000, 2500, 700, impact_ms=1162),
        GrantedAction('Ruination', 0, 30000, 2500, 780, 'Rend', impact_ms=1029,
                      unlock_duration_ms=20000),
        GrantedAction('Wrath', 0, 15000, 0, 700, 'FC3', gcd=False,
                      impact_ms=1162, unlock_duration_ms=2500),
    )
    short = optimize_package(actions, ((0, 7787),), 1519, 7787)
    assert short.potency == 2060
    assert {name for name, _ in short.casts} == {'FC1', 'Rend', 'Ruination'}
    # With four slots the Wrath reward outweighs substituting a second blade.
    longer = optimize_package(actions, ((0, 11000),), 1519, 11000)
    assert longer.potency == 3140  # 3 FC + Rend + earned Wrath
    assert {name for name, _ in longer.casts} == {'FC1', 'FC2', 'FC3', 'Rend', 'Wrath'}


def test_impact_can_land_after_buff_window_but_not_after_encounter_end():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (GrantedAction('Delayed', 900, 1000, 2500, 100, impact_ms=500),)
    assert optimize_package(actions, ((0, 1000),), 0, 1000).potency == 0
    assert optimize_package(actions, ((0, 1000),), 0, 1000,
                            impact_windows=((0, 1500),)).potency == 100


def test_delaying_parent_before_downtime_can_preserve_an_earned_ready_effect():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (GrantedAction('Parent', 0, 2000, 2500, 100),
               GrantedAction('Follow', 0, 9000, 2500, 1000, 'Parent',
                             unlock_duration_ms=3500))
    plan = optimize_package(actions, ((0, 2000), (5000, 9000)), 0, 9000)
    assert plan.potency == 1100
    assert 1500 < plan.casts[0][1] < 2000
    assert plan.casts[1][1] == 5000


def test_equal_potency_and_impact_time_package_keeps_more_completed_casts():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (GrantedAction('Long GCD', 0, 1000, 5000, 1000, impact_ms=1250),
               GrantedAction('First', 0, 3000, 2500, 500),
               GrantedAction('Second', 0, 3000, 2500, 500))
    plan = optimize_package(actions, ((0, 3000),), 0, 3000)
    assert plan.potency == 1000
    assert {name for name, _ in plan.casts} == {'First', 'Second'}


def test_equal_potency_package_fills_early_weave_slots():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (GrantedAction('First GCD', 0, 6000, 2500, 1000),
               GrantedAction('Second GCD', 0, 6000, 2500, 1000, 'First GCD'),
               GrantedAction('Ability', 0, 6000, 0, 500, gcd=False))
    plan = optimize_package(actions, ((0, 6000),), 0, 6000)
    assert plan.potency == 2500
    assert plan.casts == (('First GCD', 0), ('Ability', 700), ('Second GCD', 2500))


def test_equal_potency_package_prefers_earlier_impacts():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (GrantedAction('Slow hit', 0, 1000, 2500, 500, impact_ms=1500),
               GrantedAction('Fast hit', 700, 1000, 2500, 500))
    plan = optimize_package(actions, ((0, 1000),), 0, 1000,
                            impact_windows=((0, 3000),))
    assert plan.casts == (('Fast hit', 700),)
    assert plan.potency == 500


def test_more_potency_takes_priority_over_earlier_impacts():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (GrantedAction('Early hit', 0, 1000, 2500, 500),
               GrantedAction('Stronger hit', 700, 1000, 2500, 600))
    plan = optimize_package(actions, ((0, 1000),), 0, 1000)
    assert plan.casts == (('Stronger hit', 700),)
    assert plan.potency == 600


def test_scorn_expected_ticks_make_earlier_application_more_valuable():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = (GrantedAction('Intervene', 0, 1600, 0, 150, gcd=False),
               GrantedAction('Scorn', 0, 1600, 0, 140, gcd=False,
                             tick_potency=30, dot_duration_ms=15000))
    plan = optimize_package(actions, ((0, 1600),), 0, 1600,
                            impact_windows=((0, 2000),))
    assert plan.casts == (('Scorn', 0), ('Intervene', 700))
    assert plan.potency == 310


def test_expected_ticks_continue_after_buff_but_stop_at_first_downtime():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    action = GrantedAction('Scorn', 0, 1000, 0, 140, gcd=False,
                           impact_ms=500, tick_potency=30, dot_duration_ms=15000)
    full = optimize_package((action,), ((0, 1000),), 0, 1000,
                            impact_windows=((0, 30000),))
    shortened = optimize_package((action,), ((0, 1000),), 0, 1000,
                                 impact_windows=((0, 3500), (5000, 30000)))
    assert full.potency == 290  # All five expected ticks, even after the buff.
    assert shortened.potency == 170  # Three seconds after application, no resumption.


def test_cleave_ticks_stop_at_each_targets_own_boundary():
    from ffxiv_potency.analysis.burst_opportunities import PeriodicTarget, optimize_package

    action = GrantedAction('Scorn', 0, 1000, 0, 280, gcd=False,
        tick_potency=30, dot_duration_ms=15000,
        periodic_targets=(PeriodicTarget(0, 1000, ((0, 2000),)),
                          PeriodicTarget(0, 1000, ((0, 5000),))))
    plan = optimize_package((action,), ((0, 1000),), 0, 1000,
                            impact_windows=((0, 30000),))
    assert plan.potency == 350  # Two direct hits, then 20 + 50 expected tick potency.


def test_repeated_abilities_can_use_a_recorded_cleave_moment_only_once():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = tuple(GrantedAction(str(i), 0, 10000, 0, 100, gcd=False,
        potency_windows=((5000, 5000.001, 1000),)) for i in range(3))
    plan = optimize_package(actions, ((0, 10000),), 0, 10000)
    assert plan.potency == 1200
    assert len(plan.casts) == 3


def test_ability_consumer_recast_can_prevent_a_second_use_before_downtime():
    from ffxiv_potency.analysis.burst_opportunities import optimize_package

    actions = tuple(GrantedAction(str(i), 0, 900, 0, 100, gcd=False,
        cooldown_group='Consumer', cooldown_ms=1000) for i in range(2))
    assert optimize_package(actions, ((0, 900),), 0, 900).potency == 100
    longer = tuple(GrantedAction(str(i), 0, 1100, 0, 100, gcd=False,
        cooldown_group='Consumer', cooldown_ms=1000) for i in range(2))
    assert optimize_package(longer, ((0, 1100),), 0, 1100).potency == 200


def test_window_clocks_include_buff_animation_and_hard_cast_gcd_start():
    from ffxiv_potency.analysis.burst_opportunities import opening_clocks

    names = {1: 'Holy Spirit', 2: 'Fight or Flight'}
    actions = {'Holy Spirit': {'type': 'Spell', 'cast_seconds': 1.5, 'recast_seconds': 2.5},
               'Fight or Flight': {'type': 'Ability', 'recast_seconds': 60}}
    casts = [{'type': kind, 'sourceID': 1, 'abilityGameID': ability, 'timestamp': time}
             for kind, ability, time in (('begincast', 1, -400), ('cast', 1, 1100), ('cast', 2, 2000))]
    assert opening_clocks(casts, names, actions, 1, 2000, ('Goring Blade',)) == (2700, 2100)


def test_proposed_casts_reserve_other_recorded_ability_weaves():
    from ffxiv_potency.analysis.burst_opportunities import GrantedAction, optimize_package

    actions = (GrantedAction('First', 0, 3000, 0, 100, gcd=False),
               GrantedAction('Second', 0, 3000, 0, 100, 'First', gcd=False))
    plan = optimize_package(actions, ((0, 3000),), 0, 3000, fixed_weaves=(1000,))
    assert plan.casts == (('First', 0), ('Second', 1700))
    assert plan.potency == 200
