"""Burst packages preserve landed GCD capacity at each encounter boundary."""

import pytest

from ffxiv_potency.analysis.burst_opportunities import (
    GrantedAction,
    opening_clocks,
    optimize_package,
)
from ffxiv_potency.analysis.gcd_budget import GcdBudget, gcd_capacity, recorded_gcd_budget


def package(weaves):
    actions = (GrantedAction('First', 0, 10000, 2500, 100, impact_ms=500),
               GrantedAction('Second', 0, 10000, 2500, 100, 'First', impact_ms=500),
               *(GrantedAction(f'Weave{i}', 0, 700 * weaves + 100, 0, 1000, 'First', gcd=False)
                 for i in range(weaves)))
    return actions


@pytest.mark.parametrize('weaves,end,allowed', [(2, 3100, 2), (3, 3100, 2),
                                                (3, 3700, 3), (4, 4400, 4)])
def test_extra_weaves_require_room_for_all_landed_gcds(weaves, end, allowed):
    actions = package(weaves)
    budget = GcdBudget(((0, end),), 0, impact_ms=500)
    plan = optimize_package(actions, ((0, end),), 0, end, gcd_budget=budget)
    # Generic GCDs remain protected even though only two GCDs are scored.
    counts, _ = gcd_capacity(budget, plan.casts, {a.name: a for a in actions})
    assert counts == gcd_capacity(budget, (), {})[0]
    assert sum(name.startswith('Weave') for name, _ in plan.casts) == allowed
    times = dict(plan.casts)
    between = sum(times['First'] < time < times['Second']
                  for name, time in plan.casts if name.startswith('Weave'))
    expected_between = min(allowed, 2) if end == 3100 else allowed
    assert between == expected_between


def test_clipping_after_buff_expiry_still_counts_before_downtime():
    budget = GcdBudget(((0, 5100),), 0, impact_ms=500)
    actions = package(3)
    casts = (('First', 0), ('Weave0', 700), ('Weave1', 1400), ('Weave2', 2100),
             ('Second', 2800))
    assert gcd_capacity(budget, (), {})[0] == (2,)
    assert gcd_capacity(budget, casts, {a.name: a for a in actions})[0] == (2,)
    # A tighter boundary turns the same clipping into a lost GCD.
    tight = GcdBudget(((0, 3100),), 0, impact_ms=500)
    assert gcd_capacity(tight, casts, {a.name: a for a in actions})[0] == (1,)
    assert gcd_capacity(tight, (), {})[0] == (2,)


def test_later_phase_cannot_replace_a_lost_gcd_before_hp_lock():
    budget = GcdBudget(((0, 3100), (10000, 16000)), 0, impact_ms=500)
    actions = package(3)
    casts = (('First', 0), ('Weave0', 700), ('Weave1', 1400), ('Weave2', 2100),
             ('Second', 2800))
    assert gcd_capacity(budget, casts, {a.name: a for a in actions})[0] == (1, 3)
    assert gcd_capacity(budget, (), {})[0] == (2, 3)


def test_opening_buff_weave_retains_previous_gcd_and_observed_recast():
    names = {1: 'GCD', 2: 'Fight or Flight'}
    actions = {'GCD': {'type': 'Weaponskill', 'recast_seconds': 2.5},
               'Fight or Flight': {'type': 'Ability'}}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': ability, 'timestamp': time}
             for time, ability in ((0, 1), (2460, 1), (4920, 1), (6320, 2))]
    budget = recorded_gcd_budget(casts, names, actions, 1, 6400, 10000,
                                 ((0, 15000),), 6400, {'GCD': 500})
    assert budget.recast_ms == 2460
    assert budget.windows == ((6400, 15000),)
    animation, gcd = opening_clocks(casts, names, actions, 1, 6400, (), budget.recast_ms)
    assert animation == 7020  # FoF's animation still occupies its weave slot.
    assert gcd == 7380  # Previous GCD recovers independently of the FoF cast.


def test_selected_and_filler_hits_must_land_strictly_before_boundary():
    action = GrantedAction('GCD', 0, 5000, 2500, 100, impact_ms=500)
    budget = GcdBudget(((0, 3000),), 0, impact_ms=500)
    assert gcd_capacity(budget, (), {})[0] == (1,)
    assert gcd_capacity(budget, (('GCD', 0), ('GCD', 2500)), {'GCD': action})[0] == (1,)


def test_ability_only_package_can_weave_after_an_unscored_ordinary_gcd():
    action = GrantedAction('Ability', 0, 2600, 0, 1000, gcd=False)
    budget = GcdBudget(((0, 3100),), 0, impact_ms=500)
    plan = optimize_package((action,), ((0, 2600),), 0, 2600, gcd_budget=budget)
    assert plan.casts == (('Ability', 700),)
    assert gcd_capacity(budget, plan.casts, {'Ability': action})[0] == (2,)


def test_short_downtime_does_not_reset_gcd_recovery():
    budget = GcdBudget(((0, 1000), (1500, 4000)), 0, impact_ms=500)
    assert gcd_capacity(budget, (), {})[0] == (1, 1)


def test_remaining_fast_gcd_can_recover_capacity_after_a_slow_gcd():
    actions = (GrantedAction('Slow', 0, 6000, 3000, 1000, impact_ms=500),
               GrantedAction('Fast', 0, 6000, 1000, 100, 'Slow', impact_ms=500))
    budget = GcdBudget(((0, 6000),), 0, impact_ms=500)
    assert gcd_capacity(budget, (('Slow', 0),), {'Slow': actions[0]})[0] == (2,)
    plan = optimize_package(actions, ((0, 6000),), 0, 6000, gcd_budget=budget)
    assert plan.casts == (('Slow', 0), ('Fast', 3000))
    assert gcd_capacity(budget, plan.casts, {a.name: a for a in actions})[0] == (3,)
