"""Reordered spell packages consume their own timed Requiescat charges."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis.burst_opportunities import GrantedAction, optimize_package
from ffxiv_potency.analysis.pld.package_resources import requiescat_model

ACTIONS = {a['name']: a for a in json.loads(
    Path('data/jobs/pld/7.4/actions.json').read_text())['actions']}
NAMES = {1: 'Imperator', 2: 'Confiteor', 3: 'Blade of Faith', 4: 'Blade of Truth',
         5: 'Blade of Valor', 6: 'Holy Spirit', 7: 'Clemency'}


def cast(time, ability):
    return {'type': 'cast', 'timestamp': time, 'abilityGameID': ability,
            'sourceID': 1, 'packetID': ability}


def grant(time, status=1001368):
    return {'type': 'applybuff', 'timestamp': time, 'abilityGameID': status,
            'sourceID': 1, 'targetID': 1, 'duration': 30000, 'packetID': 1}


def chain(begin=0):
    names = ('Imperator', 'Confiteor', 'Blade of Faith', 'Blade of Truth', 'Blade of Valor')
    candidates = tuple(GrantedAction(name, begin, 60000, 2500,
        ACTIONS[name]['potency']['base'], names[i - 1] if i else None,
        gcd=i > 0) for i, name in enumerate(names))
    return candidates, {name: name for name in names}


def test_reordered_fourth_spell_retains_enhancement_after_recorded_consumption():
    casts = [cast(t, i) for t, i in ((0, 1), (700, 2), (3200, 3), (5700, 4), (8200, 5))]
    buffs = [grant(0), {'type': 'removebuff', 'timestamp': 8200,
                       'targetID': 1, 'abilityGameID': 1001368}]
    configure = requiescat_model(casts, buffs, [], [], NAMES, ACTIONS, 1, 0, 60000)
    candidates, labels = chain(1000)
    candidates, resources = configure(candidates, labels, 0, 20000, labels)
    plan = optimize_package(candidates, ((0, 20000),), 0, 20000, resources=resources)
    assert dict(plan.casts)['Blade of Valor'] == 9200
    assert plan.potency == 580 + 1000 + 760 + 880 + 1000


@pytest.mark.parametrize('duration', [30000, 1500])
def test_fifth_charge_and_natural_expiry_use_base_potency(duration):
    candidates, labels = chain()
    configure = requiescat_model([], [], [], [], NAMES, ACTIONS, 1, 0, 60000)
    candidates, resources = configure(candidates, labels, 0, 20000, labels)
    imperator = candidates[0]
    from dataclasses import replace
    candidates = (replace(imperator, resource_duration_ms=duration), *candidates[1:])
    # Force five chronological spends with simple equal potencies.
    candidates = (candidates[0], *(GrantedAction(str(i), 0, 20000, 2500, 100,
        'Imperator' if i == 0 else str(i - 1), potency_resource='Requiescat',
        enhanced_potency=200) for i in range(5)))
    plan = optimize_package(candidates, ((0, 20000),), 0, 20000, resources=resources)
    # Imperator 580 + four enhanced spells + one base, or only the first enhanced.
    assert plan.potency == 580 + (900 if duration == 30000 else 600)
    assert len(plan.casts) == 6


@pytest.mark.parametrize('holy,divine,expected', [(6, False, 3), (6, True, 4), (7, False, 3)])
def test_opening_charges_account_for_holy_spirit_divine_might_and_clemency(holy, divine, expected):
    buffs = [grant(0)] + ([grant(1000, 1002673)] if divine else [])
    casts = [cast(0, 1), cast(1000, holy)]
    configure = requiescat_model(casts, buffs, [], [], NAMES, ACTIONS, 1, 0, 60000)
    _, resources = configure((), {}, 2000, 20000, ())
    assert resources[0].charges == expected
    assert resources[0].expires == 30000


@pytest.mark.parametrize('divine', [False, True])
def test_outside_package_holy_spirit_spends_only_without_divine_might(divine):
    buffs = [grant(0)] + ([grant(1000, 1002673)] if divine else [])
    configure = requiescat_model([cast(0, 1), cast(1000, 6)], buffs, [], [],
                                NAMES, ACTIONS, 1, 0, 60000)
    candidates, labels = chain()
    candidates, resources = configure(candidates, labels, 0, 20000, labels)
    plan = optimize_package(candidates, ((0, 20000),), 0, 20000, resources=resources)
    assert plan.potency == (4220 if divine else 3720)


def test_death_clears_proposed_charges():
    configure = requiescat_model([], [], [{'type': 'death', 'timestamp': 1000, 'targetID': 1}],
                                [], NAMES, ACTIONS, 1, 0, 60000)
    candidates, labels = chain()
    candidates, resources = configure(candidates, labels, 0, 20000, labels)
    plan = optimize_package(candidates, ((0, 20000),), 0, 20000, resources=resources)
    assert plan.potency == 580 + 1000 + 260 + 380 + 500


def test_refresh_replaces_remaining_charges_in_proposed_order():
    from ffxiv_potency.analysis.burst_opportunities import PotencyResource

    resource = PotencyResource('Requiescat', 1, 30000, ((1000, 4, 30000),))
    actions = tuple(GrantedAction(str(i), 0, 20000, 2500, 100,
        str(i - 1) if i else None, potency_resource='Requiescat',
        enhanced_potency=200) for i in range(6))
    plan = optimize_package(actions, ((0, 20000),), 0, 20000, resources=(resource,))
    assert plan.potency == 5 * 200 + 100


def test_enhanced_cleave_preserves_observed_additional_targets():
    configure = requiescat_model([], [grant(-1000)], [], [], NAMES, ACTIONS, 1, -1000, 60000)
    candidate = GrantedAction('Confiteor', 0, 1000, 2500, 500,
                              potency_windows=((0, 1, 700),))
    candidates, resources = configure((candidate,), {'Confiteor': 'Confiteor'}, 0, 1000,
                                     ('Confiteor',))
    plan = optimize_package(candidates, ((0, 1000),), 0, 1000, resources=resources)
    assert plan.potency == 1400


def test_initial_aura_remaining_duration_and_charges_are_retained():
    configure = requiescat_model([], [], [], [{'sourceID': 1, 'auras': [
        {'ability': 1001368, 'stacks': 2, 'duration': 5000}]}], NAMES, ACTIONS, 1, 0, 60000)
    _, resources = configure((), {}, 2000, 20000, ())
    assert resources[0].charges == 2
    assert resources[0].expires == 5000


def test_unknown_opening_expiry_is_not_presented_as_established():
    configure = requiescat_model([], [], [], [{'sourceID': 1, 'auras': [
        {'ability': 1001368, 'stacks': 2}]}], NAMES, ACTIONS, 1, 0, 60000)
    _, resources = configure((), {}, 2000, 20000, ())
    assert not resources[0].evidence_available
