"""Bound explanations by recorded grants, distinguish missing casts from hits."""

import pytest

from ffxiv_potency.analysis.diagnostics import summarize_follow_ups
from ffxiv_potency.analysis.targetability import TargetableTime

NAMES = {1: 'Last Dance Ready', 2: 'Last Dance'}
GRANT = {'type': 'applybuff', 'abilityGameID': 1, 'sourceID': 1, 'targetID': 1,
             'timestamp': 0, 'packetID': 1, 'duration': 30000}


def summary(casts=(), damage=(), buffs=(GRANT,), life=(), end=40000, intervals=None,
            failures=None):
    return summarize_follow_ups('dancer', list(casts), list(damage), list(buffs), NAMES,
        list(life), 1, 0, end, TargetableTime(end / 1000, 'events',
                                           intervals if intervals is not None else ((0, end),)),
        failures or {})


def test_absence_without_a_recorded_grant_is_not_a_missing_follow_up():
    assert summary(buffs=()) == ()
    assert summary(buffs=(dict(GRANT, sourceID=2, targetID=2),)) == ()


@pytest.mark.parametrize('life,end,intervals,reason', [
    (({'type': 'death', 'targetID': 1, 'timestamp': 10000},), 40000, None, 'player died during sequence'),
    (({'type': 'death', 'targetID': 2, 'timestamp': 10000},), 40000, None, 'Last Dance Ready expired'),
    ((), 5000, None, 'fight ended during sequence'),
    ((), 40000, ((0, 10000), (35000, 40000)), 'boss downtime during sequence'),
    ((), 40000, ((0, 10000), (20000, 40000)), 'Last Dance Ready expired'),
])
def test_context_is_bounded_and_short_downtime_does_not_explain_omission(life, end, intervals, reason):
    result = summary(life=life, end=end, intervals=intervals)
    assert len(result) == 1 and result[0].reason == reason


def test_completed_cast_without_hit_reuses_existing_hp_lock_evidence():
    cast = {'type': 'cast', 'sourceID': 1, 'abilityGameID': 2, 'timestamp': 1000, 'packetID': 2}
    result = summary(casts=(cast,), failures={('Last Dance', 1): 'phase HP lock'})
    assert len(result) == 1
    assert (result[0].seconds, result[0].outcome, result[0].reason) == (1, 'cast, no hit', 'phase HP lock')
    hit = dict(cast, type='damage', timestamp=1600, amount=1, hitType=1)
    assert summary(casts=(cast,), damage=(hit,)) == ()


def test_duplicate_grant_refresh_extends_lifetime_and_overwrite_is_distinct():
    refresh = dict(GRANT, type='refreshbuff', timestamp=500, duration=30000)
    assert len(summary(buffs=(GRANT, refresh))) == 1
    assert summary(buffs=(GRANT, dict(refresh, packetID=2, timestamp=10000)))[0].reason == 'ready effect overwritten'


def test_cast_on_new_grant_is_not_counted_for_previous_grant():
    grant = dict(GRANT, timestamp=10000, packetID=2)
    cast = {'type': 'cast', 'sourceID': 1, 'abilityGameID': 2, 'timestamp': 10000, 'packetID': 3}
    hit = dict(cast, type='damage', amount=100, hitType=1)
    result = summary(casts=(cast,), damage=(hit,), buffs=(GRANT, grant))
    assert len(result) == 1 and result[0].reason == 'ready effect overwritten'


@pytest.mark.parametrize('job,status,action,duration', [
    ('warrior', 'Primal Ruination Ready', 'Primal Ruination', 20000),
    ('bard', 'Radiant Encore Ready', 'Radiant Encore', 30000),
    ('machinist', 'Excavator Ready', 'Excavator', 30000),
    ('machinist', 'Full Metal Machinist', 'Full Metal Field', 30000),
    ('dancer', 'Flourishing Finish', 'Tillana', 30000),
    ('dancer', 'Flourishing Starfall', 'Starfall Dance', 20000),
    ('dancer', 'Dance of the Dawn Ready', 'Dance of the Dawn', 30000),
])
def test_each_job_uses_its_actual_ready_effect(job, status, action, duration):
    names = {1: status, 2: action}
    grant = dict(GRANT, duration=duration)
    row = summarize_follow_ups(job, [], [], [grant], names, [], 1, 0, 40000,
        TargetableTime(40, 'events', ((0, 40000),)), {})
    assert len(row) == 1 and row[0].reason == f'{status} expired'
    cast = {'type': 'cast', 'sourceID': 1, 'abilityGameID': 2, 'timestamp': 1000, 'packetID': 2}
    hit = dict(cast, type='damage', amount=100, hitType=1)
    assert summarize_follow_ups(job, [cast], [hit], [grant], names, [], 1, 0, 40000,
        TargetableTime(40, 'events', ((0, 40000),)), {}) == ()


def test_identical_missing_follow_up_contexts_are_grouped():
    names = {1: 'Flourishing Finish', 2: 'Dance of the Dawn Ready'}
    grants = [dict(GRANT, abilityGameID=i) for i in (1, 2)]
    rows = summarize_follow_ups('dancer', [], [], grants, names,
        [{'type': 'death', 'targetID': 1, 'timestamp': 5000}], 1, 0, 40000,
        TargetableTime(40, 'events', ((0, 40000),)), {})
    assert len(rows) == 1 and rows[0].actions == ('Tillana', 'Dance of the Dawn')


def test_partial_inner_release_tracks_casts_separately_from_hits():
    names = {1: 'Inner Release', 2: 'Fell Cleave'}
    casts = [{'type': 'cast', 'sourceID': 1, 'abilityGameID': 2,
              'timestamp': t, 'packetID': t} for t in (1000, 3000)]
    hit = dict(casts[0], type='damage', amount=100, hitType=1)
    rows = summarize_follow_ups('warrior', casts, [hit], [dict(GRANT, duration=15000)],
        names, [], 1, 0, 40000, TargetableTime(40, 'events', ((0, 40000),)), {})
    assert {r.outcome for r in rows} == {'incomplete', 'cast, no hit'}
    assert next(r for r in rows if r.outcome == 'incomplete').actions == ('Inner Release spenders: 2/3 casts',)


def test_cast_after_death_does_not_consume_an_earlier_ready_grant():
    cast = {'type': 'cast', 'sourceID': 1, 'abilityGameID': 2, 'timestamp': 10000, 'packetID': 2}
    hit = dict(cast, type='damage', amount=100, hitType=1)
    result = summary(casts=(cast,), damage=(hit,),
                     life=({'type': 'death', 'targetID': 1, 'timestamp': 5000},))
    assert len(result) == 1 and result[0].reason == 'player died during sequence'


def test_early_effect_removal_does_not_become_a_confirmed_expiry():
    removal = dict(GRANT, type='removebuff', timestamp=8000)
    rows = summary(buffs=(GRANT, removal))
    assert rows[0].reason == 'Last Dance Ready removed; reason unconfirmed'
    cast = {'type': 'cast', 'sourceID': 1, 'abilityGameID': 2, 'timestamp': 7500, 'packetID': 2}
    hit = dict(cast, type='damage', amount=100, hitType=1)
    assert summary(casts=(cast,), damage=(hit,), buffs=(GRANT, removal)) == ()


def test_effect_removed_at_death_retains_death_context():
    removal = dict(GRANT, type='removebuff', timestamp=8000)
    rows = summary(buffs=(GRANT, removal),
                   life=({'type': 'death', 'targetID': 1, 'timestamp': 8000},))
    assert rows[0].reason == 'player died during sequence'
