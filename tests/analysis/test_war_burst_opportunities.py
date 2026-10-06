"""WAR opportunity bounds preserve resources, recorded casts and encounter evidence."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis.burst_opportunities import BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.models import PotionWindow
from ffxiv_potency.analysis.penalties import life_with_revival_evidence, summarize_status_windows
from ffxiv_potency.analysis.targetability import TargetableTime
from ffxiv_potency.analysis.war.burst_opportunities import (
    summarize_ir_opportunities,
    summarize_opportunities,
)
from ffxiv_potency.analysis.war.bursts import WarBurst, WarPotionBurst

ACTIONS = {a['name']: a for a in json.loads(
    Path('data/jobs/war/7.5/actions.json').read_text())['actions']}
NAMES = {1: 'Inner Release', 2: 'Fell Cleave', 3: 'Primal Rend', 4: 'Primal Ruination',
         5: 'Primal Wrath', 6: 'Inner Chaos', 7: 'Upheaval', 8: 'Onslaught', 9: 'Infuriate'}


def cast(time, ability):
    return {'timestamp': time, 'type': 'cast', 'sourceID': 1,
            'abilityGameID': ability, 'packetID': time}


def grant(time, status, duration=30000):
    return {'timestamp': time, 'type': 'applybuff', 'sourceID': 1, 'targetID': 1,
            'abilityGameID': status, 'duration': duration}


def summary(casts=(), buffs=(), damage=(), life=(), begin=0, finish=30, counts=(), intervals=None):
    targetable = TargetableTime(120, 'test', ((0, 120000),) if intervals is None else intervals)
    return summarize_opportunities(casts, damage, buffs, life, NAMES, ACTIONS, 1, 0, 120000,
        (PotionWindow(begin, finish),), targetable,
        (WarPotionBurst(begin, finish, counts, 1000, 100, 0),))[0]


def by_name(window):
    return {action.name: action for action in window.actions}


@pytest.mark.parametrize('carry,review', [(False, True), (True, False)])
def test_potion_preparation_review_requires_charge_evidence_and_no_carried_grant(carry, review):
    casts = (cast(0, 9), cast(140000, 9), cast(142000, 6),
             cast(150000, 9), cast(152000, 6))
    buffs = [grant(0, 1001897),
             {'timestamp': 1000, 'type': 'removebuff', 'targetID': 1, 'abilityGameID': 1001897},
             grant(140000, 1001897), grant(150000, 1001897)]
    if carry:
        buffs.append(grant(125000, 1001897))
    window = summarize_opportunities(casts, (), buffs, (), NAMES, ACTIONS, 1, 0, 240000,
        (PotionWindow(130, 160),), TargetableTime(240, 'test', ((0, 240000),)),
        (WarPotionBurst(130, 160, (('Infuriate', 2), ('Nascent Chaos', 2)), 0, 0, 0),))[0]
    nc = by_name(window)['Nascent Chaos']
    assert nc.review is review
    assert nc.casts == 2
    if review:
        assert 'No Nascent Chaos carried' in nc.notes[0]
        assert '10.0s after the window started' in nc.notes[0]
        assert 'gauge room and a GCD slot' in nc.notes[0]
    assert _decode(_encode(window), BurstWindow) == window


def test_resource_grants_and_patch_stack_count_determine_opportunities():
    window = summary(buffs=(grant(0, 1001177, 15000), grant(0, 1002624)))
    rows = by_name(window)
    assert rows['IR spenders'].expected == 3
    assert rows['Primal Rend'].expected == 1
    assert rows['Nascent Chaos'].expected is None
    assert rows['Infuriate'].expected is None
    assert window.landed_potency == 1100
    assert _decode(_encode(window), BurstWindow) == window
    # Changing reference stacks changes the calculation without a rotation template.
    actions = {**ACTIONS, 'Inner Release': {**ACTIONS['Inner Release'],
        'description': ['Grants 2 stacks of Inner Release']}}
    result = summarize_opportunities([], [], [grant(0, 1001177, 15000)], [], NAMES, actions,
        1, 0, 120000, (PotionWindow(0, 30),), TargetableTime(120, 'test', ((0, 120000),)),
        (WarPotionBurst(0, 30, (), 0, 0, 0),))[0]
    assert by_name(result)['IR spenders'].expected == 2


def test_complete_ir_package_can_earn_unrecorded_wrath():
    rows = by_name(summary(buffs=(grant(0, 1001177, 15000),)))
    assert rows['IR spenders'].expected == 3
    assert rows['Primal Wrath'].expected == 1
    assert rows['Primal Wrath'].casts == 0
    assert 'could be earned' in rows['Primal Wrath'].notes[0]


def test_earned_wrath_requires_full_spender_package_and_a_living_weave_slot():
    for intervals in (((0, 4000),), ((0, 5500),)):
        rows = by_name(summary(buffs=(grant(0, 1001177, 15000),), intervals=intervals))
        assert rows['Primal Wrath'].expected == 0


def test_earned_wrath_uses_patch_unlock_threshold_and_does_not_duplicate_recorded_grants():
    description = ['Grants 2 stacks of Inner Release',
                   'Burgeoning Fury, up to a maximum of 2',
                   'At maximum stacks, become Wrathful']
    actions = {**ACTIONS, 'Inner Release': {**ACTIONS['Inner Release'],
                                         'description': description}}
    buffs = [grant(0, 1001177, 15000), grant(5000, 1003901, 30000)]
    result = summarize_opportunities([], [], buffs, [], NAMES, actions, 1, 0, 120000,
        (PotionWindow(0, 30),), TargetableTime(120, 'test', ((0, 120000),)),
        (WarPotionBurst(0, 30, (), 0, 0, 0),))[0]
    assert by_name(result)['IR spenders'].expected == 2
    assert by_name(result)['Primal Wrath'].expected == 1
    assert not by_name(result)['Primal Wrath'].notes


def test_package_selects_higher_potency_when_only_one_gcd_fits():
    rows = by_name(summary(buffs=(grant(0, 1001177, 15000), grant(0, 1002624)),
                           finish=2, intervals=((0, 2000),)))
    assert rows['Primal Rend'].expected == 1
    assert rows['IR spenders'].expected == 0


def test_grant_consumed_before_potion_is_not_spent_again():
    rows = by_name(summary(casts=(cast(1000, 3),), buffs=(grant(0, 1002624),), begin=10))
    assert rows['Primal Rend'].expected == 0


@pytest.mark.parametrize('life, intervals', [
    (({'timestamp': 5000, 'type': 'death', 'targetID': 1},), None),
    ((), ((0, 5000), (40000, 120000))),
])
def test_death_and_downtime_prevent_unrecorded_grant_uses(life, intervals):
    rows = by_name(summary(buffs=(grant(0, 1002624),), begin=10,
                           life=life, intervals=intervals))
    assert rows['Primal Rend'].expected == 0


def test_ruination_opportunity_after_wipe_uses_next_cast_revival_bound():
    life = [{'timestamp': 5000, 'type': 'death', 'targetID': 1}]
    casts = [cast(11000, 3)]
    statuses = summarize_status_windows([], life, NAMES, 1, 0, 120000, casts)
    effective = life_with_revival_evidence(life, statuses, 1, 0)
    rows = by_name(summary(casts=casts, buffs=(grant(11000, 1003834, 20000),),
                           life=effective, begin=10, finish=35))
    assert rows['Primal Ruination'].casts == 0
    assert rows['Primal Ruination'].expected == 1


@pytest.mark.parametrize('finish, expected', [(30, 0), (33, 1)])
def test_ruination_grant_respects_recorded_rend_gcd_before_fight_end(finish, expected):
    rend = cast(29000, 3)
    ready = {**grant(29000, 1003834, 20000), 'packetID': rend['packetID'],
             'extraAbilityGameID': 3}
    rows = by_name(summary(casts=(rend,), buffs=(ready,), finish=finish))
    assert rows['Primal Ruination'].casts == 0
    assert rows['Primal Ruination'].expected == expected


def test_outside_cleave_keeps_alignment_unknown_and_does_not_accuse_loss():
    event = cast(35000, 3)
    damage = tuple({**event, 'type': 'damage', 'targetID': target, 'amount': 100}
                   for target in (2, 3))
    rows = by_name(summary(casts=(event,), buffs=(grant(0, 1002624, 40000),), damage=damage))
    assert rows['Primal Rend'].expected is None


def test_hits_exclude_calculated_events_and_include_later_impacts():
    event = cast(29000, 3)
    damage = ({**event, 'timestamp': 31000, 'type': 'damage', 'amount': 100},
              {**event, 'type': 'calculateddamage', 'amount': 100})
    rows = by_name(summary(casts=(event, event), damage=damage,
                           counts=(('Primal Rend', 1),)))
    assert rows['Primal Rend'].casts == 1
    assert rows['Primal Rend'].hits == 1


def test_later_cooldown_use_is_preserved_and_missing_opening_charges_unknown():
    rows = by_name(summary(casts=(cast(-10000, 7), cast(31000, 7),), begin=20))
    assert rows['Upheaval/Orogeny'].expected == 0
    assert rows['Onslaught'].expected is None


def test_ir_pre_pull_expectations_remain_unknown_and_round_trip():
    result = summarize_ir_opportunities([cast(1000, 2)], [], [], [], NAMES, ACTIONS,
        1, 0, 60000, TargetableTime(60, 'test', ((0, 60000),)),
        (WarBurst(None, 1, 0, 0, 0),))
    assert all(row.expected is None for row in result[0].actions)
    assert _decode(_encode(result[0]), BurstWindow) == result[0]


def test_snapshot_linked_cast_before_potion_boundary_keeps_its_landed_hit():
    event = cast(9900, 3)
    burst = WarPotionBurst(10, 40, (('Primal Rend', 1),), 1000, 100, 0,
                           (('Primal Rend', ((9900, 3),)),))
    rows = summarize_opportunities([event], [{**event, 'type': 'damage', 'amount': 100}],
        [], [], NAMES, ACTIONS, 1, 0, 120000, (PotionWindow(10, 40),),
        TargetableTime(120, 'test', ((0, 120000),)), (burst,))
    action = by_name(rows[0])['Primal Rend']
    assert (action.casts, action.hits, action.expected) == (1, 1, 1)


def prepull(casts, damage=(), buffs=(), opening=(), counts=(3, 1, 1, 1)):
    return summarize_ir_opportunities(casts, damage, buffs, [], NAMES, ACTIONS,
        1, 0, 60000, TargetableTime(60, 'test', ((0, 60000),)),
        (WarBurst(None, *counts),), [{'sourceID': 1, 'auras': [{'ability': x} for x in opening]}])[0]


def test_pre_pull_completion_confirmed_by_opening_buffs_and_linked_ir_hits():
    casts = [cast(time, 2) for time in (10000, 12500, 15000)]
    casts += [cast(16000, 5), cast(30000, 3), cast(45000, 4)]
    damage = [{**event, 'type': 'damage', 'amount': 100,
               'buffs': '1001177.' if event['abilityGameID'] == 2 else ''} for event in casts]
    buffs = [grant(15000, 1003901), grant(30000, 1003834, 20000)]
    row = prepull(casts, damage, buffs, (1001177, 1002624))
    assert [action.expected for action in row.actions] == [3, 1, 1, 1]
    assert [action.hits for action in row.actions] == [3, 1, 1, 1]
    assert _decode(_encode(row), BurstWindow) == row


def test_pre_pull_lucky_direct_crits_do_not_establish_ir_spending():
    casts = [cast(time, 2) for time in (1000, 3500, 6000)]
    damage = [{**event, 'type': 'damage', 'amount': 100, 'hitType': 2, 'directHit': True}
              for event in casts]
    row = prepull(casts, damage, opening=(1001177,), counts=(3, 0, 0, 0))
    assert by_name(row)['IR spenders'].expected is None


def test_partial_pre_pull_spending_is_not_assumed_to_have_three_opportunities():
    event = cast(1000, 2)
    hit = {**event, 'type': 'damage', 'amount': 100, 'buffs': '1001177.'}
    row = prepull([event], [hit], opening=(1001177,), counts=(1, 0, 0, 0))
    assert by_name(row)['IR spenders'].expected is None


def test_ghosted_pre_pull_spender_snapshot_confirms_cast_but_not_landed_hit():
    casts = [cast(time, 2) for time in (1000, 3500, 6000)]
    damage = [{**event, 'type': 'damage' if index < 2 else 'calculateddamage',
               'amount': 100, 'buffs': '1001177.'} for index, event in enumerate(casts)]
    row = prepull(casts, damage, opening=(1001177,), counts=(3, 0, 0, 0))
    action = by_name(row)['IR spenders']
    assert (action.casts, action.expected, action.hits) == (3, 3, 2)


def test_pre_pull_stack_consumption_can_confirm_casts_without_hit_records():
    casts = [cast(time, 2) for time in (1000, 3500, 6000)]
    buffs = [{'timestamp': event['timestamp'], 'type': 'removebuffstack', 'targetID': 1,
              'abilityGameID': 1001177, 'stack': remaining}
             for event, remaining in zip(casts[:2], (2, 1))]
    last = {**casts[-1], 'type': 'calculateddamage', 'buffs': '1001177.'}
    row = prepull(casts, [last], buffs, (1001177,), counts=(3, 0, 0, 0))
    assert (by_name(row)['IR spenders'].expected, by_name(row)['IR spenders'].hits) == (3, 0)


def test_pre_pull_cast_before_saved_start_retains_later_landed_hit():
    casts = [cast(time, 2) for time in (-312, 2000, 4500)]
    damage = [{**event, 'timestamp': event['timestamp'] + 700, 'type': 'damage',
               'amount': 100, 'buffs': '1001177.'} for event in casts]
    action = by_name(prepull(casts, damage, opening=(1001177,), counts=(3, 0, 0, 0)))['IR spenders']
    assert (action.casts, action.expected, action.hits) == (3, 3, 3)


def test_short_ir_ending_compares_reordered_rend_ruination_with_recorded_package():
    actions = {a['name']: a for a in json.loads(
        Path('data/jobs/war/7.4/actions.json').read_text())['actions']}
    names = {**NAMES, 10: "Storm's Eye"}
    casts = [cast(-10000, 4), cast(-9000, 5), cast(-981, 10), cast(0, 1),
             cast(1476, 2), cast(3938, 2), cast(6444, 3)]
    damage = [{**e, 'timestamp': e['timestamp'] + delay, 'type': 'damage', 'amount': 100}
              for e, delay in ((casts[0], 1029), (casts[1], 1162),
                               (casts[4], 626), (casts[5], 626), (casts[6], 1162))]
    ready = {**grant(6444, 1003834, 20000), 'packetID': 6444, 'extraAbilityGameID': 3}
    result = summarize_ir_opportunities(casts, damage,
        [grant(0, 1001177, 15000), grant(0, 1002624), ready], [], names, actions,
        1, 0, 7787, TargetableTime(7.787, 'test', ((0, 7787),)),
        (WarBurst(0, 2, 1, 0, 0),))[0]
    rows = by_name(result)
    assert rows['IR spenders'].expected == 1
    assert rows['Primal Rend'].expected == 1
    assert rows['Primal Ruination'].expected == 1
    assert rows['Primal Wrath'].expected == 0
    assert result.actual_package_potency == 1860
    assert result.best_package_potency == 2060
    assert _decode(_encode(result), BurstWindow) == result
    from ffxiv_potency.reporting import burst_completion
    assert burst_completion(result) == '90.3%'
