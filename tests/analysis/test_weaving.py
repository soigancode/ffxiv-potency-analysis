"""Recorded utility abilities move with their surrounding proposed GCD."""

from ffxiv_potency.analysis.burst_opportunities import GrantedAction, optimize_package
from ffxiv_potency.analysis.weaving import attach_weaves


def event(time, ability):
    return {'type': 'cast', 'timestamp': time, 'abilityGameID': ability, 'sourceID': 1}


def test_other_ability_follows_moved_gcd_and_reserves_its_weave_slot():
    actions = {'First': {'type': 'Spell'}, 'Second': {'type': 'Spell'},
               'Damage': {'type': 'Ability'}, 'Guardian': {'type': 'Ability'}}
    names = {1: 'First', 2: 'Guardian', 3: 'Second', 4: 'Damage'}
    casts = [event(0, 1), event(900, 2), event(2500, 3)]
    candidates = (GrantedAction('a', 0, 10000, 2500, 100),
                  GrantedAction('b', 1000, 10000, 2500, 200, 'a'),
                  GrantedAction('c', 1000, 10000, 0, 50, 'a', gcd=False))
    configured, labels, fixed = attach_weaves(candidates,
        {'a': 'First', 'b': 'Second', 'c': 'Damage'}, casts, names, actions, 0, 10000)
    plan = optimize_package(configured, ((0, 10000),), 1000, 10000, fixed_weaves=fixed)
    assert plan.potency == 350
    assert dict(plan.casts)['a'] == 1000
    assert plan.weaves == ((configured[0].weave_offsets[0][0], 1700),)
    assert labels[plan.weaves[0][0]] == 'Guardian'
    assert all(abs(time - 1700) >= 700 for _, time in plan.casts)
    assert fixed == ()


def test_second_weave_stays_second_and_repeated_gcds_keep_distinct_weaves():
    actions = {'Fell Cleave': {'type': 'Weaponskill'},
               'Upheaval': {'type': 'Ability'}, 'Rampart': {'type': 'Ability'}}
    names = {1: 'Fell Cleave', 2: 'Upheaval', 3: 'Rampart'}
    casts = [event(0, 1), event(700, 2), event(1450, 3), event(2500, 1), event(3250, 3)]
    candidates = (GrantedAction('a', 0, 10000, 2500, 580),
                  GrantedAction('b', 0, 10000, 2500, 580, 'a'),
                  GrantedAction('c', 0, 10000, 0, 420, gcd=False))
    configured, labels, _ = attach_weaves(candidates,
        {'a': 'IR spenders', 'b': 'IR spenders', 'c': 'Upheaval'}, casts, names, actions,
        0, 10000, {'Fell Cleave': 'IR spenders'})
    assert [offset for _, offset in configured[0].weave_offsets] == [1400]
    assert [offset for _, offset in configured[1].weave_offsets] == [700]
    assert all(labels[key] == 'Rampart' for c in configured for key, _ in c.weave_offsets)


def test_ability_without_a_package_gcd_keeps_its_existing_reservation():
    configured, labels, fixed = attach_weaves((), {}, [event(1000, 1)], {1: 'Rampart'},
        {'Rampart': {'type': 'Ability'}}, 0, 10000)
    assert configured == () and labels == {} and fixed == (1000,)


def test_weave_expiry_preserves_a_later_followup_duration():
    actions = (GrantedAction('Parent', 0, 10000, 2500, 100,
                             weave_offsets=(('Rampart', 700),)),
               GrantedAction('Child', 5000, 10000, 0, 200, 'Parent', gcd=False,
                             unlock_duration_ms=6000))
    plan = optimize_package(actions, ((0, 10000),), 0, 10000)
    assert plan.casts == (('Parent', 0), ('Child', 5000))
    assert plan.weaves == (('Rampart', 700),)
    assert plan.potency == 300


def test_pre_pull_weave_uses_its_negative_cast_time():
    actions = (GrantedAction('Parent', -1000, 4000, 2500, 100,
                             weave_offsets=(('Rampart', 700),)),
               GrantedAction('Child', -1000, 4000, 0, 50, 'Parent', gcd=False))
    plan = optimize_package(actions, ((-1000, 4000),), -1000, 4000)
    assert plan.casts == (('Parent', -1000), ('Child', 400))
    assert plan.weaves == (('Rampart', -300),)


def test_resource_activation_is_not_moved_after_an_unbuffed_spender():
    casts = [dict(event(0, 1), packetID=8), dict(event(700, 2), packetID=9)]
    candidates = (GrantedAction('a', 700, 10000, 2500, 580),)
    configured, _, fixed = attach_weaves(candidates, {'a': 'IR spenders'}, casts,
        {1: 'Fell Cleave', 2: 'Inner Release'},
        {'Fell Cleave': {'type': 'Weaponskill'}, 'Inner Release': {'type': 'Ability'}},
        0, 10000, {'Fell Cleave': 'IR spenders'}, {(8, 1)})
    assert configured[0].weave_offsets == ()
    assert fixed == (700,)


def test_resource_grant_does_not_move_without_a_resource_replay():
    candidates = (GrantedAction('a', 0, 10000, 2500, 700),)
    configured, _, fixed = attach_weaves(candidates, {'a': 'Nascent Chaos'},
        [event(0, 1), event(700, 2)], {1: 'Inner Chaos', 2: 'Infuriate'},
        {'Inner Chaos': {'type': 'Weaponskill'}, 'Infuriate': {'type': 'Ability'}},
        0, 10000, {'Inner Chaos': 'Nascent Chaos'}, fixed_names=('Infuriate',))
    assert configured[0].weave_offsets == ()
    assert fixed == (700,)


def test_carried_action_reserves_time_even_when_the_same_action_is_a_candidate():
    candidates = (GrantedAction('honor', 0, 10000, 0, 1000, gcd=False),)
    cast = dict(event(700, 1), packetID=7)
    configured, _, fixed = attach_weaves(candidates, {'honor': 'Blade of Honor'},
        [cast], {1: 'Blade of Honor'}, {'Blade of Honor': {'type': 'Ability'}},
        0, 10000, fixed_casts={(7, 1)})
    assert fixed == (700,)
    plan = optimize_package(configured, ((0, 10000),), 0, 10000, fixed_weaves=fixed)
    assert abs(plan.casts[0][1] - 700) >= 700
