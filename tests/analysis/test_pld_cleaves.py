"""Held PLD follow-ups retain their original grant and actual enhancement."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ffxiv_potency.analysis.burst_opportunities import BurstAction, BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.pld.cleaves import compare_held_cleaves
from ffxiv_potency.reporting import held_cleave_note


def example():
    actions = {a['name']: a for a in json.loads(Path('data/jobs/pld/7.4/actions.json').read_text())['actions']}
    names = dict(enumerate(('Confiteor', 'Blade of Faith', 'Blade of Truth', 'Blade of Valor', 'Blade of Honor'), 1))
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': ability, 'packetID': ability,
              'timestamp': time} for ability, time in ((1, 3000), (2, 6000), (3, 9000), (4, 40000), (5, 50000))]
    hits = [{**e, 'type': 'damage', 'targetID': target, 'amount': 100,
             'buffs': '1000076.1000049.' if e['abilityGameID'] == 5 else ''}
            for e in casts[-2:] for target in (2, 3)]
    rows = [(h, h['timestamp'], names[h['abilityGameID']], value)
            for h, value in zip(hits, (500, 200, 1350, 540))]
    buffs = [{'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1003831,
              'timestamp': 40000, 'duration': 30000},
             {'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1000049,
              'timestamp': 45000, 'duration': 30000}]
    window = BurstWindow(0, 20, (BurstAction('Blade of Valor', 0, 0, None),
                                BurstAction('Blade of Honor', 0, 0, None)), 0,
        proposed_order=(('Imperator', 1), ('Confiteor', 2),
        ('Blade of Faith', 4.5), ('Blade of Truth', 7), ('Blade of Valor', 9.5), ('Blade of Honor', 10.2)))
    args = (casts, hits, rows, names, actions, 1, 0, {},
            {1000076: ((0, 20000, 1.25), (45000, 65000, 1.25))}, buffs, [], [],
            SimpleNamespace(potion_buff_id=1000049, player_potion_multiplier=1.08,
                            party_main_stat=6000, potted_main_stat=6500), {})
    return window, args


def test_expired_req_cleave_loses_but_honor_in_next_buff_and_potion_gains():
    window, args = example()
    result = compare_held_cleaves((window,), *args)[0]
    valor, honor = result.held_cleaves
    assert valor.held_potency == 700
    assert valor.earlier_potency == 1250
    assert valor.enhancement == 'None'
    assert honor.held_potency == 1890
    assert honor.earlier_potency == 1250
    assert honor.held_effects == ('Fight or Flight', 'potion')
    assert sum(c.held_potency - c.earlier_potency for c in result.held_cleaves) == 90
    assert result.actual_package_potency is None and result.best_package_potency is None
    assert [a.expected for a in result.actions] == [0, 0]
    assert _decode(_encode(result), BurstWindow) == result
    note = held_cleave_note(result, honor, lambda seconds: str(seconds))
    assert note.startswith('Held for cleave at 50.0: 2 targets.')
    assert 'Holding gained 640.0 potency' in note
    assert 'Held follow-ups together: 90.0 potency gained' in note


@pytest.mark.parametrize('duration,expected', [(30000, 1350), (1000, 1250)])
def test_earlier_potion_is_counted_only_while_active(duration, expected):
    window, args = example()
    args[9].append({'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1000049,
                    'timestamp': 0, 'duration': duration})
    result = compare_held_cleaves((window,), *args)[0]
    assert result.held_cleaves[0].earlier_potency == pytest.approx(expected)


def test_next_confiteor_prevents_borrowing_its_valor():
    window, args = example()
    args[0].append({'type': 'cast', 'sourceID': 1, 'abilityGameID': 1, 'packetID': 10, 'timestamp': 35000})
    assert not compare_held_cleaves((window,), *args)[0].held_cleaves


@pytest.mark.parametrize('reason', ['expired', 'overwritten'])
def test_expired_or_overwritten_honor_grant_is_not_attributed_to_previous_chain(reason):
    window, args = example()
    if reason == 'expired':
        args[9][0]['duration'] = 5000
    else:
        args[0].append({'type': 'cast', 'sourceID': 1, 'abilityGameID': 4,
                        'timestamp': 47000, 'packetID': 11})
    result = compare_held_cleaves((window,), *args)[0]
    assert [c.name for c in result.held_cleaves] == ['Blade of Valor']


def test_earlier_use_must_be_in_feasible_package():
    window, args = example()
    window = replace(window, proposed_order=tuple(row for row in window.proposed_order if row[0] != 'Blade of Valor'))
    result = compare_held_cleaves((window,), *args)[0]
    assert [c.name for c in result.held_cleaves] == ['Blade of Honor']
