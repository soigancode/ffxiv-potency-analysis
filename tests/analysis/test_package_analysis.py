"""Cross-job packages respect dependency clocks and damageable boundaries."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ffxiv_potency.analysis.burst_opportunities import BurstAction, BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.package_analysis import (
    PackageRules,
    exclude_trailing_hp_lock_casts,
    summarize_packages,
)
from ffxiv_potency.analysis.targetability import TargetableTime, package_targetable_time


def test_carried_ready_effect_is_not_earned_again_in_receiving_package():
    names = {1: 'Generator', 2: 'Follow-up'}
    actions = {'Generator': {'type': 'Ability', 'recast_seconds': 10, 'potency': {'base': 100}},
               'Follow-up': {'type': 'Ability', 'recast_seconds': 1, 'potency': {'base': 1000}}}
    casts = [{'type': 'cast', 'sourceID': 1, 'targetID': 2, 'abilityGameID': ability,
              'timestamp': time, 'packetID': packet}
             for ability, time, packet in ((2, 500, 1), (1, 2000, 2), (2, 3000, 3))]
    damage = [{**e, 'type': 'damage', 'amount': 100} for e in casts]
    buffs = [{'type': 'applybuff', 'sourceID': 1, 'targetID': 1, 'abilityGameID': 9,
              'timestamp': time, 'duration': 30000} for time in (-5000, 2000)]
    window, = summarize_packages(casts, damage, buffs, [], names, actions, 1, 0, 5000,
        ((0, 5000),), TargetableTime(5, 'test', ((0, 5000),)),
        PackageRules(('Generator',), (('Ready', ('Follow-up',), 1),),
                     status_ids=(('Ready', 9),), earned=(('Generator', 'Follow-up', 1),)),
        fixed_casts={(1, 2)})
    followup = next(a for a in window.actions if a.name == 'Follow-up')
    assert (followup.casts, followup.hits, followup.expected) == (1, 1, 1)
    assert window.actual_package_potency == window.best_package_potency == 1100
    assert ('Follow-up', .5) not in window.recorded_order


def test_scorn_comparison_uses_same_tick_estimate_for_recorded_and_proposed_casts():
    names = {1: 'Circle of Scorn'}
    actions = {'Circle of Scorn': {'type': 'Ability', 'recast_seconds': 30,
        'potency': {'base': 140, 'damage_over_time': {'potency_per_tick': 30,
                                                     'duration_seconds': 15}}}}
    casts = [{'type': 'cast', 'sourceID': 1, 'targetID': 2, 'abilityGameID': 1,
              'timestamp': time, 'packetID': packet}
             for time, packet in ((-30000, 1), (2000, 2))]
    damage = [{**e, 'type': 'damage', 'timestamp': e['timestamp'] + 500, 'amount': 100}
              for e in casts]
    window = summarize_packages(casts, damage, [], [], names, actions, 1, 0, 10000,
        ((0, 4000),), TargetableTime(10, 'test', ((0, 10000),)),
        PackageRules(('Circle of Scorn',), (), periodic=('Circle of Scorn',)),
        periodic_target_windows={(2, 1): ((0, 6000),)})[0]
    assert window.actual_package_potency == 175  # Application at 2500, 3.5s of ticks.
    assert window.best_package_potency == 195  # Application at 500, 5.5s of ticks.
    assert window.proposed_order == (('Circle of Scorn', 0),)
    assert window.actions[0].hits == 1
    assert window.periodic_actions == ('Circle of Scorn',)
    assert _decode(_encode(window), BurstWindow) == window
    from ffxiv_potency.reporting import package_completion_note
    note = package_completion_note(window)
    assert 'Recorded / proposed potency: 175.0 / 195.0.' in note
    assert 'until HP lock, untargetability or expiry' in note


@pytest.mark.parametrize('later_reason,other_target,landed', [
    ('phase HP lock', False, False),
    ('reason unconfirmed', False, False),
    ('phase HP lock', True, False),
    ('phase HP lock', False, True),
])
def test_only_later_confirmed_hp_lock_ghosts_leave_package_counts(later_reason, other_target, landed):
    names = {1: 'Blade of Honor', 2: 'Goring Blade', 3: 'Intervene'}
    casts = [{'type': 'cast', 'sourceID': 1, 'targetID': 2, 'timestamp': time,
              'abilityGameID': ability, 'packetID': ability}
             for time, ability in ((1000, 1), (2000, 2), (3000, 3))]
    if other_target:
        casts[1]['targetID'] = 3
    damage = [{**casts[1], 'type': 'damage', 'targetID': 3, 'amount': 100}] if landed else []
    endings = (('Blade of Honor', ((1, 'phase HP lock'),)),
               ('Goring Blade', ((2, later_reason),)),
               ('Intervene', ((3, 'phase HP lock'),)))
    order = tuple((names[e['abilityGameID']], e['timestamp'] / 1000) for e in casts)
    window = BurstWindow(0, 5, tuple(BurstAction(name, 1, int(landed and ability == 2),
        int(ability == 1)) for ability, name in names.items()), 0, 0, 1000,
        recorded_order=order, proposed_order=order)
    result = exclude_trailing_hp_lock_casts((window,), casts, damage, names, 1, 0, endings)[0]
    honor, goring, intervene = result.actions
    assert honor.casts == honor.package_casts == 1
    assert goring.casts == 1
    assert goring.excluded_casts == int(later_reason == 'phase HP lock' and not other_target and not landed)
    assert intervene.excluded_casts == int(not landed)
    assert result.best_package_potency == window.best_package_potency
    assert result.recorded_order == order
    assert len(result.proposed_order) == len(order) - sum(a.excluded_casts for a in result.actions)
    assert _decode(_encode(result), BurstWindow) == result


@pytest.mark.parametrize('job,first,second,status', [
    ('pld', 'Fast Blade', 'Confiteor', 'Confiteor Ready'),
    ('brd', 'Refulgent Arrow', 'Blast Arrow', 'Blast Arrow Ready'),
    ('mch', 'Blazing Shot', 'Full Metal Field', 'Full Metal Machinist'),
    ('dnc', 'Last Dance', 'Dance of the Dawn', 'Dance of the Dawn Ready'),
])
def test_short_package_uses_reference_potency_and_hit_delays(job, first, second, status):
    actions = {a['name']: a for a in json.loads(
        Path(f'data/jobs/{job}/7.4/actions.json').read_text())['actions']}
    names = {1: first, 2: second, 3: status, 4: 'Other Ready'}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': 2,
              'packetID': 7, 'timestamp': -3000}]
    damage = [{**casts[0], 'type': 'damage', 'timestamp': -2000, 'amount': 100}]
    buffs = [{'type': 'applybuff', 'sourceID': 1, 'targetID': 1, 'timestamp': 0,
              'abilityGameID': id_, 'duration': 30000} for id_ in (3, 4)]
    rules = PackageRules((), ((status, (second,), 1), ('Other Ready', (first,), 1)))
    common = (casts, damage, buffs, [], names, actions, 1, 0, 10000)
    # A slow second action cannot land before a 500ms damageable boundary.
    short = summarize_packages(*common, ((0, 500),),
        TargetableTime(.5, 'test', ((0, 500),)), rules)[0]
    assert next(a for a in short.actions if a.name == second).expected == 0
    longer = summarize_packages(*common, ((0, 1500),),
        TargetableTime(1.5, 'test', ((0, 1500),)), rules)[0]
    assert next(a for a in longer.actions if a.name == second).expected == 1
    assert longer.best_package_potency == actions[second]['potency']['base']
    assert _decode(_encode(longer), BurstWindow) == longer
    assert importlib.import_module(f'ffxiv_potency.analysis.{job}.package_rules').RULES


def test_hp_lock_closes_at_observed_threshold_and_keeps_other_enemy_available():
    boss = {'type': 'NPC', 'subType': 'Boss'}
    actors = {2: boss, 3: boss}
    damage = [{'type': 'damage', 'targetID': 2, 'timestamp': 0, 'amount': 100},
              {'type': 'damage', 'targetID': 3, 'timestamp': 0, 'amount': 100}]
    overkills = [{'targetID': 2, 'timestamp': 5000, 'amount': 100, 'overkill': 1}]
    locks = {2: [(2500, 9000)]}
    original = TargetableTime(10, 'test', ((0, 10000),))
    both = package_targetable_time(original, actors, damage, [], overkills, locks, 0, 10000)
    assert both.intervals == ((0, 10000),)
    alone = package_targetable_time(original, {2: boss}, damage[:1], [{'type': 'targetabilityupdate', 'sourceID': 2, 'timestamp': 9000, 'targetable': 1}], overkills,
                                   locks, 0, 10000)
    assert alone.intervals == ((0, 5000), (9000, 10000))
    assert original.seconds == 10


def test_reference_stack_count_changes_hypercharge_package_without_rotation_template():
    names = {1: 'Overheated', 2: 'Blazing Shot'}
    rules = PackageRules((), (('Overheated', ('Blazing Shot',), 5),))
    actions = {'Hypercharge': {'description': ['Grants 2 stacks of Overheated']},
               'Blazing Shot': {'type': 'Weaponskill', 'recast_seconds': 1.5,
                               'potency': {'base': 220}}}
    buffs = [{'type': 'applybuff', 'targetID': 1, 'sourceID': 1, 'timestamp': 0,
              'abilityGameID': 1, 'duration': 10000}]
    result = summarize_packages([], [], buffs, [], names, actions, 1, 0, 10000,
        ((0, 10000),), TargetableTime(10, 'test', ((0, 10000),)), rules)[0]
    assert result.actions[0].expected == 2
    assert result.best_package_potency == 440
    assert result.recorded_order == ()
    assert result.proposed_order == (('Blazing Shot', 0.0), ('Blazing Shot', 1.5))
    assert _decode(json.loads(json.dumps(_encode(result))), BurstWindow) == result


def test_barrage_multihit_potency_is_counted_once():
    from ffxiv_potency.analysis.brd.package_rules import rules_for_actions

    actions = {a['name']: a for a in json.loads(
        Path('data/jobs/brd/7.4/actions.json').read_text())['actions']}
    names = {1: 'Barrage', 2: 'Refulgent Arrow'}
    cast = {'type': 'cast', 'timestamp': 1000, 'sourceID': 1, 'abilityGameID': 2, 'packetID': 8}
    damage = [{**cast, 'type': 'damage', 'timestamp': 1100, 'amount': 100} for _ in range(3)]
    buffs = [{'type': 'applybuff', 'timestamp': 0, 'targetID': 1, 'sourceID': 1,
              'abilityGameID': 1, 'duration': 10000}]
    rules = rules_for_actions(actions)
    rules = PackageRules((), (rules.ready[0],), multipliers=rules.multipliers)
    result = summarize_packages([cast], damage, buffs, [], names, actions, 1, 0, 10000,
        ((0, 10000),), TargetableTime(10, 'test', ((0, 10000),)), rules)[0]
    assert result.actual_package_potency == result.best_package_potency == 840


def test_package_overkill_uses_established_primary_target_for_travelling_aoe():
    cast = {'type': 'cast', 'timestamp': 1000, 'sourceID': 1,
            'abilityGameID': 2, 'packetID': 8}
    secondary = {**cast, 'type': 'damage', 'targetID': 3, 'amount': 100,
                 'overkill': 100, 'timestamp': 1100}
    primary = {**cast, 'type': 'damage', 'targetID': 4, 'amount': 500,
               'timestamp': 1200}
    actions = {'Cleave': {'type': 'Weaponskill', 'recast_seconds': 2.5,
                         'potency': {'base': 1000, 'falloff': {'additional_target_multiplier': .4}}}}
    result = summarize_packages([cast], [secondary, primary], [], [], {2: 'Cleave'},
        actions, 1, 0, 10000, ((0, 10000),), TargetableTime(10, 'test', ((0, 10000),)),
        PackageRules((), (), witnessed=('Cleave',)), primary_hits={(8, 2): primary})[0]
    assert result.actual_package_potency == result.best_package_potency == 1200


def test_enhanced_potency_priority_changes_when_effect_expires():
    names = {1: 'A', 2: 'B', 3: 'A Ready', 4: 'B Ready'}
    actions = {'A': {'type': 'Spell', 'recast_seconds': 2.5, 'potency': {'base': 100}},
               'B': {'type': 'Weaponskill', 'recast_seconds': 2.5, 'potency': {'base': 700}}}
    buffs = [{'type': 'applybuff', 'timestamp': 0, 'targetID': 1, 'sourceID': 1,
              'abilityGameID': n, 'duration': 10000} for n in (3, 4)]
    rules = PackageRules((), (('A Ready', ('A',), 1), ('B Ready', ('B',), 1)))
    kwargs = {'enhancements': {'A': ((0, 1000, 1200),)}}
    result = summarize_packages([], [], buffs, [], names, actions, 1, 0, 10000,
        ((0, 1500),), TargetableTime(1.5, 'test', ((0, 1500),)), rules, **kwargs)[0]
    assert result.actions[0].expected == 1
    assert result.best_package_potency == 1200


def test_paired_hp_lock_uses_shared_threshold_instead_of_later_boss_lethal_hit():
    actors = {n: {'type': 'NPC', 'subType': 'Boss'} for n in (2, 3)}
    damage = [{'type': 'damage', 'targetID': n, 'timestamp': 0, 'amount': 100} for n in (2, 3)]
    overkills = [{'targetID': n, 'timestamp': t, 'overkill': 1, 'amount': 100}
                 for n, t in ((2, 5000), (3, 7000))]
    result = package_targetable_time(TargetableTime(10, 'test', ((0, 10000),)),
        actors, damage, [], overkills, {2: [(2500, 9000)], 3: [(2500, 9000)]}, 0, 10000)
    assert result.intervals == ((0, 5000),)


def test_outside_cleave_keeps_burst_expectation_unknown():
    names = {1: 'Blast Arrow', 2: 'Blast Arrow Ready'}
    actions = {'Blast Arrow': {'type': 'Weaponskill', 'recast_seconds': 2.5,
                              'potency': {'base': 700, 'falloff': {'additional_target_multiplier': .5}}}}
    cast = {'type': 'cast', 'timestamp': 21000, 'sourceID': 1, 'abilityGameID': 1, 'packetID': 8}
    damage = [{**cast, 'type': 'damage', 'amount': 100, 'targetID': target} for target in (3, 4)]
    buffs = [{'type': 'applybuff', 'timestamp': 0, 'targetID': 1, 'sourceID': 1,
              'abilityGameID': 2, 'duration': 30000}]
    result = summarize_packages([cast], damage, buffs, [], names, actions, 1, 0, 60000,
        ((0, 20000),), TargetableTime(60, 'test', ((0, 60000),)),
        PackageRules((), (('Blast Arrow Ready', ('Blast Arrow',), 1),)))[0]
    assert result.actions[0].expected is None
    assert result.best_package_potency is None


def test_cleave_potency_stays_at_recorded_cast_moment():
    names = {1: 'Cleave', 2: 'Cleave Ready'}
    actions = {'Cleave': {'type': 'Weaponskill', 'recast_seconds': 2.5,
                         'potency': {'base': 700, 'falloff': {'additional_target_multiplier': .5}}}}
    cast = {'type': 'cast', 'timestamp': 5000, 'sourceID': 1, 'abilityGameID': 1, 'packetID': 8}
    damage = [{**cast, 'type': 'damage', 'timestamp': 5100, 'amount': 100, 'targetID': n}
              for n in (3, 4)]
    buffs = [{'type': 'applybuff', 'timestamp': 0, 'targetID': 1, 'sourceID': 1,
              'abilityGameID': 2, 'duration': 10000}]
    rules = PackageRules((), (('Cleave Ready', ('Cleave',), 1),))
    result = summarize_packages([cast], damage, buffs, [], names, actions, 1, 0, 10000,
        ((0, 10000),), TargetableTime(10, 'test', ((0, 10000),)), rules)[0]
    assert result.best_package_potency == result.actual_package_potency == 1050
    # A later ready grant cannot reuse targets observed at the earlier cast.
    refreshed = [*buffs, {**buffs[0], 'timestamp': 5100, 'type': 'refreshbuff'}]
    second = summarize_packages([cast], damage, refreshed, [], names, actions, 1, 0, 10000,
        ((0, 6000),), TargetableTime(10, 'test', ((0, 10000),)), rules)[0]
    assert second.best_package_potency == 1400
    assert second.actions[0].expected == 2


def test_deterministic_gauge_reward_is_earned_without_double_counting_recorded_spend():
    names = {1: 'Tillana', 2: 'Saber Dance', 3: 'Flourishing Finish'}
    actions = {'Tillana': {'type': 'Weaponskill', 'recast_seconds': 2.5, 'potency': {'base': 600}},
               'Saber Dance': {'type': 'Weaponskill', 'recast_seconds': 2.5, 'potency': {'base': 520}}}
    buffs = [{'type': 'applybuff', 'timestamp': 0, 'targetID': 1, 'sourceID': 1,
              'abilityGameID': 3, 'duration': 30000}]
    rules = PackageRules((), (('Flourishing Finish', ('Tillana',), 1),),
                         witnessed=('Saber Dance',), earned=(('Tillana', 'Saber Dance', 1),))
    result = summarize_packages([], [], buffs, [], names, actions, 1, 0, 10000,
        ((0, 10000),), TargetableTime(10, 'test', ((0, 10000),)), rules)[0]
    assert [a.expected for a in result.actions] == [1, 1]
    assert result.best_package_potency == 1120


@pytest.mark.parametrize('opening', [False, True])
def test_recorded_ready_reward_is_not_added_again_for_same_parent(opening):
    names = {1: 'Valor', 2: 'Honor', 3: 'Valor Ready', 4: 'Honor Ready'}
    actions = {'Valor': {'type': 'Weaponskill', 'recast_seconds': 2.5, 'potency': {'base': 1000}},
               'Honor': {'type': 'Ability', 'recast_seconds': 1, 'potency': {'base': 1000}}}
    casts = [{'type': 'cast', 'timestamp': 8000, 'sourceID': 1, 'abilityGameID': 1, 'packetID': 8}]
    buffs = [{'type': 'applybuff', 'timestamp': 0, 'targetID': 1, 'sourceID': 1,
              'abilityGameID': 3, 'duration': 30000},
             {'type': 'applybuff', 'timestamp': 8000, 'targetID': 1, 'sourceID': 1,
              'abilityGameID': 4, 'duration': 30000, 'packetID': 8, 'extraAbilityGameID': 1}]
    if opening:
        buffs.append({'type': 'applybuff', 'timestamp': -1000, 'targetID': 1, 'sourceID': 1,
                      'abilityGameID': 4, 'duration': 30000})
    rules = PackageRules((), (('Valor Ready', ('Valor',), 1), ('Honor Ready', ('Honor',), 1)),
                         earned=(('Valor', 'Honor', 1),))
    result = summarize_packages(casts, [], buffs, [], names, actions, 1, 0, 20000,
        ((0, 20000),), TargetableTime(20, 'test', ((0, 20000),)), rules)[0]
    assert next(a.expected for a in result.actions if a.name == 'Honor') == (2 if opening else 1)
    assert result.best_package_potency == (3000 if opening else 2000)


def test_mch_packages_use_wildfire_and_potions_instead_of_consumed_reassemble_window():
    from ffxiv_potency.analysis.all_packages import summarize_job_packages

    result = SimpleNamespace(
        mch_wildfires=(SimpleNamespace(applied_seconds=1),),
        potion=SimpleNamespace(windows=(SimpleNamespace(start_seconds=0, end_seconds=30),)),
    )
    groups = summarize_job_packages('machinist', result, [], [], [], [], {}, {},
        1, 0, 30000, TargetableTime(30, 'test', ((0, 30000),)), {})
    assert [name for name, _ in groups] == ['Wildfire', 'Potion']


@pytest.mark.parametrize('time,value', [(3000, 1000), (5000, None)])
def test_pld_package_respects_replayed_enhancement_and_requiescat_consumption(monkeypatch, time, value):
    from ffxiv_potency.analysis.all_packages import summarize_job_packages
    from ffxiv_potency.analysis.pld import package_rules
    from ffxiv_potency.analysis.pld.buffs import FIGHT_OR_FLIGHT

    monkeypatch.setattr(package_rules, 'RULES', PackageRules((), (('Confiteor Ready', ('Confiteor',), 1),)))
    actions = {'Confiteor': {'type': 'Spell', 'recast_seconds': 2.5,
        'potency': {'base': 400, 'conditional_potencies': {'Requiescat': 1000}}}}
    names = {1: 'Confiteor', 2: 'Confiteor Ready'}
    cast = {'type': 'cast', 'timestamp': time, 'sourceID': 1, 'abilityGameID': 1, 'packetID': 8}
    damage = [{**cast, 'type': 'damage', 'timestamp': time + 500, 'amount': 100}]
    buffs = [{'type': 'applybuff', 'sourceID': 1, 'targetID': 1, 'timestamp': 0,
              'abilityGameID': id_, 'duration': 30000} for id_ in (2, 1001368)]
    buffs.append({'type': 'removebuff', 'targetID': 1, 'timestamp': 3000, 'abilityGameID': 1001368})
    groups = summarize_job_packages('paladin', SimpleNamespace(potion=None),
        [cast], damage, buffs, [], names, actions, 1, 0, 10000,
        TargetableTime(10, 'test', ((0, 10000),)), {FIGHT_OR_FLIGHT: ((time, 10000, 1.25),)},
        spell_potencies={(8, 1): value})
    window = groups[0][1][0]
    assert window.actual_package_potency == window.best_package_potency == (value or 400)


def test_ready_resource_selects_cleave_then_single_target_without_double_spending():
    names = {1: 'Blazing Shot', 2: 'Auto Crossbow', 3: 'Overheated'}
    actions = {name: {'type': 'Weaponskill', 'recast_seconds': 1.5, 'potency': {'base': potency}}
               for name, potency in (('Blazing Shot', 220), ('Auto Crossbow', 140))}
    cast = {'type': 'cast', 'sourceID': 1, 'abilityGameID': 2, 'packetID': 8, 'timestamp': 5000}
    damage = [{**cast, 'type': 'damage', 'timestamp': 5100, 'amount': 100, 'targetID': target}
              for target in (4, 5, 6)]
    buffs = [{'type': kind, 'sourceID': 1, 'targetID': 1, 'timestamp': time,
              'abilityGameID': 3, 'duration': 10000}
             for kind, time in (('applybuff', 0), ('refreshbuff', 6000))]
    rules = PackageRules((), (('Overheated', ('Blazing Shot', 'Auto Crossbow'), 1),))
    window = summarize_packages([cast], damage, buffs, [], names, actions, 1, 0, 10000,
        ((0, 10000),), TargetableTime(10, 'test', ((0, 10000),)), rules)[0]
    assert window.actual_package_potency == 420
    assert window.best_package_potency == 640
    assert [a.expected for a in window.actions] == [1, 1]


def test_ready_ability_carries_its_pre_window_recast_into_a_short_window():
    names = {1: 'Consumer', 2: 'Ready'}
    actions = {'Consumer': {'type': 'Ability', 'recast_seconds': 1, 'potency': {'base': 100}}}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': 1, 'timestamp': -500}]
    buffs = [{'type': 'applybuff', 'sourceID': 1, 'targetID': 1, 'abilityGameID': 2,
              'timestamp': 0, 'duration': 1000}]
    rules = PackageRules((), (('Ready', ('Consumer',), 1),))
    common = (casts, [], buffs, [], names, actions, 1, 0, 1000)
    targetable = TargetableTime(1, 'test', ((0, 1000),))
    short = summarize_packages(*common, ((0, 400),), targetable, rules)[0]
    assert short.actions[0].expected == 0
    longer = summarize_packages(*common, ((0, 600),), targetable, rules)[0]
    assert longer.actions[0].expected == 1


def test_equally_strong_recorded_package_does_not_flag_an_alternative_composition():
    names = {1: 'Last Dance', 2: 'Saber Dance', 3: 'Last Dance Ready'}
    actions = {name: {'type': 'Weaponskill', 'recast_seconds': 2.5, 'potency': {'base': 520}}
               for name in ('Last Dance', 'Saber Dance')}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': 2, 'packetID': i,
              'timestamp': time} for i, time in enumerate((0, 2500))]
    damage = [{**e, 'type': 'damage', 'timestamp': e['timestamp'] + 500, 'amount': 100} for e in casts]
    buffs = [{'type': 'applybuff', 'sourceID': 1, 'targetID': 1, 'abilityGameID': 3,
              'timestamp': 0, 'duration': 10000}]
    rules = PackageRules((), (('Last Dance Ready', ('Last Dance',), 1),), witnessed=('Saber Dance',))
    window = summarize_packages(casts, damage, buffs, [], names, actions, 1, 0, 10000,
        ((0, 5000),), TargetableTime(10, 'test', ((0, 10000),)), rules)[0]
    assert window.actual_package_potency == window.best_package_potency == 1040
    assert [a.expected for a in window.actions] == [0, 2]
    assert window.recorded_order == (('Saber Dance', 0.0), ('Saber Dance', 2.5))
    assert window.proposed_order == window.recorded_order


def test_order_context_includes_recorded_weaves_and_exact_encounter_boundaries():
    from ffxiv_potency.analysis.package_analysis import annotate_package_orders

    names = {1: 'Confiteor', 2: 'Guardian', 3: 'Holy Sheltron', 4: 'Holy Spirit'}
    casts = [{'type': 'cast', 'sourceID': 1, 'timestamp': 10000 + time,
              'abilityGameID': ability, 'targetID': target, 'packetID': ability}
             for time, ability, target in ((0, 1, 7), (700, 2, 1), (1400, 3, 1), (5000, 4, 7))]
    casts.extend([dict(casts[1]), {**casts[2], 'sourceID': 2}, {**casts[1], 'fake': True}])
    actions = {name: {'type': 'Ability' if id_ in {2, 3} else 'Spell'}
               for id_, name in names.items()}
    actors = {7: {'name': 'Kefka', 'type': 'NPC'}, 8: {'name': 'Other', 'type': 'NPC'}}
    targetability = [{'sourceID': target, 'targetable': 0, 'timestamp': time}
                     for target, time in ((7, 14500), (8, 14000))]
    overkills = [{'targetID': 7, 'timestamp': 13000, 'overkill': 10},
                {'targetID': 7, 'timestamp': 13200, 'overkill': 10}]
    window = BurstWindow(0, 10, (BurstAction('Confiteor', 1, 1, 1),), 1000, 1000, 1000,
                         recorded_order=(('Confiteor', 0),), proposed_order=(('Confiteor', 0),))
    result = annotate_package_orders((window,), casts, names, actions, actors, 1, 10000,
                                     targetability, overkills, {7: ((10500, 14500),)})[0]
    assert result.recorded_order == (('Confiteor', 0), ('Guardian', .7), ('Holy Sheltron', 1.4))
    assert result.proposed_order == result.recorded_order
    assert result.boundary_events == (('HP lock reached: Kefka', 3), ('Untargetable: Kefka', 4.5))
    assert result.best_package_potency == window.best_package_potency
    assert _decode(_encode(result), BurstWindow) == result


def test_sequence_hit_times_use_linked_positive_direct_hits_only():
    from ffxiv_potency.analysis.package_analysis import annotate_package_orders

    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': 1, 'timestamp': 1000,
              'packetID': 9, 'targetID': 2}]
    direct = {**casts[0], 'type': 'damage', 'amount': 100, 'timestamp': 1700}
    damage = [direct, {**direct, 'timestamp': 1800, 'targetID': 3},
              {**direct, 'timestamp': 2000, 'tick': True}, {**direct, 'sourceID': 4},
              {**direct, 'packetID': 10}, {**direct, 'amount': 0}]
    actions = {'Confiteor': {'type': 'Spell', 'potency': {'base': 500}}}
    window = BurstWindow(0, 10, (BurstAction('Confiteor', 1, 2, 1),), 1000,
                         recorded_order=(('Confiteor', 1),), proposed_order=(('Confiteor', 1),))
    result = annotate_package_orders((window,), casts, {1: 'Confiteor'}, actions,
                                     {}, 1, 0, (), (), {}, damage)[0]
    assert result.recorded_timings[0].hit_seconds == (1.7, 1.8)
    assert result.proposed_timings == result.recorded_timings
    assert not result.proposed_timings[0].projected
    assert _decode(_encode(result), BurstWindow) == result


def test_non_damaging_grant_keeps_its_weave_when_not_a_proposed_spend():
    from ffxiv_potency.analysis.package_analysis import annotate_package_orders

    window = BurstWindow(0, 10, (BurstAction('Infuriate', 1, 0, None),
        BurstAction('Inner Chaos', 1, 1, 1)), 700,
        recorded_order=(('Infuriate', 1), ('Inner Chaos', 2)),
        proposed_order=(('Nascent Chaos', 2),))
    casts = [{'type': 'cast', 'timestamp': 1000, 'sourceID': 1,
              'abilityGameID': 1, 'packetID': 1}]
    result = annotate_package_orders((window,), casts, {1: 'Infuriate'},
        {'Infuriate': {'type': 'Ability', 'potency': None}}, {}, 1, 0, (), (), {})[0]
    assert result.proposed_order == (('Infuriate', 1), ('Nascent Chaos', 2))
