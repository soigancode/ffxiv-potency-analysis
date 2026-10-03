"""Explicit combo evidence, multi-target hits and base potency loss accounting."""

import pytest

from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.pld.combos import PldComboSummary, summarize_combos

NAMES = {1: 'Riot Blade', 2: 'Royal Authority', 3: 'Prominence'}
ACTIONS = {name: {'potency': {'base': base, 'combo': {'potency': combo}}}
           for name, base, combo in [('Riot Blade', 170, 330),
                                    ('Royal Authority', 200, 460), ('Prominence', 100, 220)]}


def hit(ability=1, **fields):
    return {'type': 'damage', 'sourceID': 1, 'abilityGameID': ability,
            'amount': 1000, 'bonusPercent': 0, **fields}


def test_landed_base_losses_include_overkill_and_each_aoe_target():
    r = summarize_combos([hit(), hit(), hit(2, overkill=1000),
                          hit(3, targetID=2), hit(3, targetID=3),
                          hit(2, bonusPercent=56)], ACTIONS, NAMES, 1)
    assert {c.name: (c.hits, c.potency_lost) for c in r.losses} == {
        'Riot Blade': (2, 320), 'Royal Authority': (1, 130), 'Prominence': (2, 240),
    }
    assert _decode(_encode(r), PldComboSummary) == r


@pytest.mark.parametrize('bonus', [None, '0', -1])
def test_missing_or_invalid_bonus_is_unconfirmed(bonus):
    damage = [hit(bonusPercent=bonus), hit()]
    del damage[1]['bonusPercent']
    r = summarize_combos(damage, ACTIONS, NAMES, 1)
    assert r.losses == ()
    assert r.unconfirmed_hits == 2


@pytest.mark.parametrize('fields', [
    {'amount': 0}, {'amount': -1}, {'type': 'calculateddamage'}, {'type': 'cast'},
    {'sourceID': 2}, {'tick': True}, {'fake': True}, {'hitType': 10},
])
def test_non_landed_or_other_source_records_do_not_create_losses(fields):
    r = summarize_combos([hit(**fields)], ACTIONS, NAMES, 1)
    assert r.losses == () and r.unconfirmed_hits == 0


def test_uses_reference_potencies_instead_of_fixed_loss_values():
    actions = {'Riot Blade': {'potency': {'base': 180, 'combo': {'potency': 350}}}}
    r = summarize_combos([hit()], actions, NAMES, 1)
    assert r.losses[0].potency_lost == 170


def inference_setup():
    from copy import deepcopy

    from ffxiv_potency.analysis.profiles import _load_combat_profile

    actions = {**deepcopy(ACTIONS), 'Fast Blade': {'potency': {'base': 220}}}
    names = {**NAMES, 4: 'Fast Blade'}
    references = [hit(4, timestamp=t, targetID=2, hitType=1, multiplier=1,
                      amount=2200, packetID=t) for t in (0, 1000, 2000)]
    return actions, names, references, _load_combat_profile('paladin')


@pytest.mark.parametrize('ability,potency', [(1, 170), (1, 330), (2, 200), (2, 460),
                                            (3, 100), (3, 220)])
def test_damage_inference_selects_base_or_combo_without_replacing_recorded_evidence(ability, potency):
    from ffxiv_potency.analysis.pld.combos import infer_combos

    actions, names, refs, profile = inference_setup()
    unknown = hit(ability, timestamp=4000, targetID=2, hitType=1, multiplier=1,
                  amount=potency * 10)
    del unknown['bonusPercent']
    inferred = infer_combos([*refs, unknown], actions, names, 1, 0, profile)
    assert inferred[id(unknown)].potency == potency
    assert inferred[id(unknown)].references == 3
    summary = summarize_combos([unknown], actions, names, 1, inferred)
    assert summary.unconfirmed_hits == 0 and len(summary.inferred) == 1
    assert _decode(_encode(summary), PldComboSummary) == summary
    unknown['bonusPercent'] = 0
    assert infer_combos([*refs, unknown], actions, names, 1, 0, profile) == {}


@pytest.mark.parametrize('changes', [{'targetID': 3}, {'targetInstance': 2},
                                    {'timestamp': 100000}, {'overkill': 1},
                                    {'targetResources': {'hitPoints': 1}},
                                    {'hitType': 10}, {'multiplier': None}])
def test_no_inference_from_incompatible_or_clipped_evidence(changes):
    from ffxiv_potency.analysis.pld.combos import infer_combos

    actions, names, refs, profile = inference_setup()
    unknown = hit(timestamp=4000, targetID=2, hitType=1, multiplier=1, amount=3300,
                  bonusPercent=None)
    unknown.update(changes)
    assert infer_combos([*refs, unknown], actions, names, 1, 0, profile) == {}


def test_sparse_inconsistent_and_ambiguous_references_remain_unresolved():
    from ffxiv_potency.analysis.pld.combos import infer_combos

    actions, names, refs, profile = inference_setup()
    unknown = hit(timestamp=4000, targetID=2, hitType=1, multiplier=1, amount=3300,
                  bonusPercent=None)
    assert infer_combos([*refs[:2], unknown], actions, names, 1, 0, profile) == {}
    refs[0]['amount'] = 100
    assert infer_combos([*refs, unknown], actions, names, 1, 0, profile) == {}
    refs[0]['amount'] = 2200
    actions['Riot Blade']['potency'] = {'base': 320, 'combo': {'potency': 340}}
    assert infer_combos([*refs, unknown], actions, names, 1, 0, profile) == {}


def test_inference_removes_crit_dh_raid_buffs_potion_weakness_and_food_difference():
    from ffxiv_potency.analysis.pld.combos import infer_combos

    actions, names, refs, profile = inference_setup()
    factor = lambda stat: 100 + profile.player_damage_coefficient * (
        stat - profile.level_main) // profile.level_main
    weak = factor(profile.potted_main_stat * 75 // 100) / factor(profile.potted_main_stat)
    amount = (3300 * profile.unfed_critical_damage_multiplier * 1.25 * 1.2
              * profile.player_potion_multiplier * weak / profile.unfed_determination_ratio)
    unknown = hit(timestamp=4000, targetID=2, hitType=2, directHit=True,
                  multiplier=1.2 * 1.05 * .75, amount=amount, bonusPercent=None,
                  buffs=f'{profile.potion_buff_id}.1000043.')
    inferred = infer_combos([*refs, unknown], actions, names, 1, 0, profile, ((3000, 5000),))
    assert inferred[id(unknown)].potency == 330
