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
