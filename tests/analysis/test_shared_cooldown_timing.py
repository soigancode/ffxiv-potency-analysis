"""Recorded recharge reductions and per-job timing eligibility."""

import pytest

from ffxiv_potency.analysis.cooldown_timing import cooldown_timing
from ffxiv_potency.analysis.diagnostics import summarize_timing
from ffxiv_potency.analysis.targetability import TargetableTime


def test_reductions_advance_recharge_without_banking_time_at_cap():
    row = cooldown_timing('Test', (0, 70000), 60000, 1, 0, 140000,
                          ((0, 140000),), ((30000, 15000), (60000, 15000)))
    assert row.ready_seconds == 35  # 45-70 and 130-140; second reduction is capped.
    assert row.longest_delay_seconds == 25


def test_reduction_at_cast_boundary_and_overlarge_reduction():
    row = cooldown_timing('Test', (0, 30000), 60000, 1, 0, 100000,
                          ((0, 100000),), ((30000, 60000),))
    assert row.ready_seconds == 10


@pytest.mark.parametrize('landed,expected', [(True, 6), (False, 1)])
def test_infuriate_reduction_uses_landed_time_and_one_aoe_packet(landed, expected):
    casts = [{'sourceID': 1, 'abilityGameID': 1, 'packetID': 1, 'timestamp': 0},
             {'sourceID': 1, 'abilityGameID': 2, 'packetID': 2, 'timestamp': 59000}]
    damage = [{'type': 'damage', 'sourceID': 1, 'abilityGameID': 2, 'packetID': 2,
                   'timestamp': 60000, 'amount': 100 if landed else 0, 'hitType': 1, 'targetID': t}
              for t in (2, 3)]
    names = {1: 'Infuriate', 2: 'Decimate'}
    actions = {'Infuriate': {'recast_seconds': 60, 'description': ['Maximum Charges: 2']}}
    row = summarize_timing('warrior', casts, damage, actions, names, [], 1, 0, 121000,
                           TargetableTime(121, 'events', ((0, 121000),)))[0]
    assert row.ready_seconds == expected
    assert row.minimum


@pytest.mark.parametrize('job,action', [('warrior', 'Inner Release'), ('bard', 'Raging Strikes'),
                                      ('machinist', 'Drill'), ('dancer', 'Devilment')])
def test_all_jobs_keep_unknown_opening_wait_and_death_exclusion(job, action):
    casts = [{'sourceID': 1, 'abilityGameID': 1, 'timestamp': 20000}]
    life = [{'type': 'death', 'targetID': 1, 'timestamp': 80000},
            {'type': 'resurrect', 'targetID': 1, 'timestamp': 90000}]
    row = summarize_timing(job, casts, [], {action: {'recast_seconds': 60}}, {1: action},
                           life, 1, 0, 100000,
                           TargetableTime(100, 'events', ((0, 100000),)))[0]
    assert row.ready_seconds == row.longest_delay_seconds == 10


@pytest.mark.parametrize('job,buff,attack', [
    ('warrior', 'Inner Release', 'Upheaval'),
    ('bard', 'Raging Strikes', 'Sidewinder'),
    ('machinist', 'Reassemble', 'Drill'),
    ('dancer', 'Devilment', None),
])
def test_shared_timing_uses_action_availability_and_still_excludes_deaths(job, buff, attack):
    actions = {buff: {'recast_seconds': 60, 'potency': None}}
    names = {1: buff}
    casts = [{'timestamp': 0, 'sourceID': 1, 'abilityGameID': 1}]
    if attack:
        names[2] = attack
        actions[attack] = {'recast_seconds': 60, 'potency': {'base': 100}}
        casts.append({'timestamp': 0, 'sourceID': 1, 'abilityGameID': 2})
    life = [{'type': 'death', 'targetID': 1, 'timestamp': 85000},
            {'type': 'resurrect', 'targetID': 1, 'timestamp': 95000}]
    debuffs = [{'timestamp': time, 'type': kind, 'targetID': 1, 'abilityGameID': 1000774}
               for time, kind in [(30000, 'applydebuff'), (80000, 'removedebuff')]]
    rows = summarize_timing(job, casts, [], actions, names, life, 1, 0, 120000,
        TargetableTime(60, 'events', ((0, 30000), (90000, 120000))), debuffs)
    rows = {row.name: row for row in rows}
    assert rows[buff].ready_seconds == rows[buff].longest_delay_seconds == 30
    if attack:
        label = 'Upheaval/Orogeny' if attack == 'Upheaval' else attack
        assert rows[label].ready_seconds == rows[label].longest_delay_seconds == 25
