"""Cross-job combo inference, explicit evidence and resource propagation."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.combos import ComboSummary
from ffxiv_potency.analysis.diagnostics import combo_summary, infer_job_combos, proc_damage
from ffxiv_potency.analysis.profiles import _load_combat_profile

CASES = [('warrior', 'war', 'Maim', 'Heavy Swing'),
         ('machinist', 'mch', 'Heated Clean Shot', 'Heated Split Shot'),
         ('dancer', 'dnc', 'Fountain', 'Cascade')]


def setup(job, code, combo, reference):
    actions = {a['name']: a for a in json.loads(
        Path(f'data/jobs/{code}/7.4/actions.json').read_text())['actions']}
    names = {1: reference, 2: combo}
    base = actions[reference]['potency']['base']
    refs = [{'type': 'damage', 'sourceID': 1, 'targetID': 2, 'targetInstance': 1,
                 'abilityGameID': 1, 'packetID': i, 'timestamp': i * 1000,
                 'amount': base * 10, 'multiplier': 1, 'hitType': 1} for i in (1, 2, 3)]
    unknown = dict(refs[-1], abilityGameID=2, packetID=4, timestamp=4000)
    return actions, names, refs, unknown, _load_combat_profile(job)


@pytest.mark.parametrize('job,code,combo,reference', CASES)
@pytest.mark.parametrize('comboed', [False, True])
def test_unique_damage_fit_and_previous_gcd(job, code, combo, reference, comboed):
    actions, names, refs, unknown, profile = setup(job, code, combo, reference)
    p = actions[combo]['potency']
    unknown['amount'] = (p['combo']['potency'] if comboed else p['base']) * 10
    damage = [*refs, unknown]
    snapshot = deepcopy(damage)
    inferences = infer_job_combos(job, damage, actions, names, 1, 0, profile, (), set())
    assert inferences[id(unknown)].comboed == comboed
    casts = [dict(e, type='cast') for e in damage]
    summary = combo_summary(damage, casts, actions, names, 1, inferences)
    assert summary.inferred[0].previous_gcd == reference
    assert summary.inferred[0].potency_lost == (0 if comboed else p['combo']['potency'] - p['base'])
    assert _decode(_encode(summary), ComboSummary) == summary
    assert damage == snapshot


@pytest.mark.parametrize('job,code,combo,reference', CASES)
def test_recorded_zero_and_clipped_damage_are_not_inferred(job, code, combo, reference):
    actions, names, refs, unknown, profile = setup(job, code, combo, reference)
    unknown['amount'] = actions[combo]['potency']['base'] * 10
    unknown['bonusPercent'] = 0
    assert infer_job_combos(job, [*refs, unknown], actions, names, 1, 0, profile, (), set()) == {}
    summary = combo_summary([unknown], [], actions, names, 1, {})
    assert summary.losses[0].hits == 1
    del unknown['bonusPercent']
    unknown['overkill'] = 10
    assert infer_job_combos(job, [*refs, unknown], actions, names, 1, 0, profile, (), set()) == {}
    assert combo_summary([unknown], [], actions, names, 1, {}).unconfirmed_hits == 1


def test_guaranteed_packets_do_not_anchor_normal_damage_inference():
    actions, names, refs, unknown, profile = setup(*CASES[1])
    unknown['amount'] = actions['Heated Clean Shot']['potency']['combo']['potency'] * 10
    packets = {(e['packetID'], e['abilityGameID']) for e in refs}
    assert infer_job_combos('machinist', [*refs, unknown], actions, names, 1, 0,
                           profile, (), packets) == {}


def test_dancer_proc_resolution_receives_inferred_packet_without_mutating_input():
    actions, names, refs, unknown, profile = setup(*CASES[2])
    unknown['amount'] = actions['Fountain']['potency']['combo']['potency'] * 10
    damage = [*refs, unknown]
    inferences = infer_job_combos('dancer', damage, actions, names, 1, 0, profile, (), set())
    calculated = dict(unknown, type='calculateddamage', timestamp=3900)
    copied = proc_damage([calculated, unknown], inferences)
    assert [e['bonusPercent'] for e in copied] == [1, 1]
    assert 'bonusPercent' not in unknown and 'bonusPercent' not in calculated
    calculated['bonusPercent'] = 0
    assert proc_damage([calculated], inferences)[0]['bonusPercent'] == 0


def test_conflicting_multi_target_combo_fits_remain_unresolved():
    actions, names, refs, first, profile = setup(*CASES[2])
    first['amount'] = actions['Fountain']['potency']['base'] * 10
    second = dict(first, targetID=3, amount=actions['Fountain']['potency']['combo']['potency'] * 10)
    other_refs = [dict(e, targetID=3) for e in refs]
    result = infer_job_combos('dancer', [*refs, *other_refs, first, second], actions, names,
                             1, 0, profile, (), set())
    assert result == {}


@pytest.mark.parametrize('comboed', [False, True])
def test_machinist_hypercharge_bonus_is_removed_from_combo_damage_fit(comboed):
    actions, names, refs, unknown, profile = setup(*CASES[1])
    modifiers = {(e['packetID'], e['abilityGameID']): 20 for e in [*refs, unknown]}
    for e in refs:
        e['amount'] += 200
    potency = actions['Heated Clean Shot']['potency']
    base = potency['combo']['potency'] if comboed else potency['base']
    unknown['amount'] = (base + 20) * 10
    result = infer_job_combos('machinist', [*refs, unknown], actions, names, 1, 0,
                             profile, (), set(), modifiers)
    assert result[id(unknown)].potency == base
    assert result[id(unknown)].comboed == comboed
