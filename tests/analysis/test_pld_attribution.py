"""Follow-up ownership survives holds and crossing a subsequent buff window."""

import pytest

from ffxiv_potency.analysis.burst_opportunities import BurstAction, BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.pld.attribution import attribute_followups
from ffxiv_potency.reporting import add_followup_tooltips


@pytest.mark.parametrize('targets', [0, 1, 2])
def test_held_honor_and_valor_count_in_granting_window_once(targets):
    names = {1: 'Confiteor', 2: 'Blade of Faith', 3: 'Blade of Truth', 4: 'Blade of Valor', 5: 'Blade of Honor'}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': ability, 'packetID': packet,
              'timestamp': time} for ability, packet, time in
             ((1, 1, 3000), (2, 2, 6000), (3, 3, 9000), (4, 4, 40000), (5, 5, 50000),
              (1, 6, 53000), (2, 7, 56000), (3, 8, 59000), (4, 9, 61000), (5, 10, 62000))]
    buffs = [{'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1003019,
              'timestamp': 0, 'duration': 30000},
             {'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1003019,
              'timestamp': 45000, 'duration': 30000},
             *({'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1003831,
                'timestamp': time, 'duration': 30000} for time in (40000, 61000))]
    damage = [{**c, 'type': 'damage', 'targetID': target, 'amount': 100}
              for c in casts if c['abilityGameID'] in (4, 5) for target in range(2, 2 + targets)]
    windows = (BurstWindow(0, 20, (BurstAction('Blade of Valor', 0, 0, None),
                                   BurstAction('Blade of Honor', 0, 0, None)), 100),
               BurstWindow(45, 65, (BurstAction('Blade of Valor', 1, targets, 1),
                                    BurstAction('Blade of Honor', 2, 2 * targets, 2)), 200))
    first, second = attribute_followups(windows, casts, buffs, damage, names, 1, 0)
    assert [(a.casts, a.hits, a.expected) for a in first.actions] == [(1, targets, 1), (1, targets, 1)]
    assert [(a.casts, a.hits, a.expected) for a in second.actions] == [(1, targets, 1), (1, targets, 1)]
    assert [c.cast_seconds for c in first.held_casts] == [40, 50]
    assert first.landed_potency == 100 and second.landed_potency == 200
    assert [(c.name, c.cast_seconds) for c in second.carried_casts] == [('Blade of Honor', 50)]
    assert _decode(_encode(first), BurstWindow) == first
    assert _decode(_encode(second), BurstWindow) == second
    if not targets:
        notes = add_followup_tooltips({}, (first, second),
            ((50, ('Blade of Honor',), 'First hit blocked by the HP lock.'),))
        assert (0, 4) in notes and (1, 4) not in notes


def test_expired_honor_ready_is_not_borrowed_from_previous_chain():
    names = {1: 'Confiteor', 2: 'Blade of Valor', 3: 'Blade of Honor'}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': ability,
              'packetID': ability, 'timestamp': time}
             for ability, time in ((1, 3000), (2, 10000), (3, 50000))]
    buffs = [{'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1003831,
              'timestamp': 10000, 'duration': 30000}]
    windows = (BurstWindow(0, 20, (BurstAction('Blade of Honor', 0, 0, 0),), 0),
               BurstWindow(45, 65, (BurstAction('Blade of Honor', 1, 0, 1),), 0))
    first, second = attribute_followups(windows, casts, buffs, [], names, 1, 0)
    assert first.actions[0].casts == 0
    assert second.actions[0].casts == 1


def test_held_confiteor_keeps_imperator_grant_window():
    names = {1: 'Imperator', 2: 'Confiteor'}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': ability,
              'packetID': ability, 'timestamp': time} for ability, time in ((1, 19000), (2, 46000))]
    grant = {'type': 'applybuff', 'targetID': 1, 'abilityGameID': 1003019,
             'timestamp': 19000, 'duration': 30000, 'packetID': 1, 'extraAbilityGameID': 1}
    windows = (BurstWindow(0, 20, (BurstAction('Confiteor', 0, 0, 0),), 0),
               BurstWindow(45, 65, (BurstAction('Confiteor', 1, 0, 1),), 0))
    first, second = attribute_followups(windows, casts, [grant], [], names, 1, 0)
    assert first.actions[0].casts == 1 and second.actions[0].casts == 0
