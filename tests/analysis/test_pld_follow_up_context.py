"""Missing follow-ups retain evidence, uncertainty and sequence boundaries."""

from dataclasses import replace

import pytest

from ffxiv_potency.analysis.execution import ReadyUse
from ffxiv_potency.analysis.pld.follow_ups import follow_up_issues
from ffxiv_potency.analysis.pld.summary import PldFollowUp
from ffxiv_potency.analysis.targetability import TargetableTime

NAMES = {1: 'Imperator', 2: 'Confiteor', 3: 'Blade of Faith', 4: 'Blade of Truth',
         5: 'Blade of Valor', 6: 'Blade of Honor'}


def issues(*, end=60000, finish=None, life=(), intervals=(), ready=(), buffs=(),
           failures=None, missing=('Blade of Truth', 'Blade of Valor'), no_hit=(),
           trigger_id=1):
    trigger = {'timestamp': 1000, 'abilityGameID': trigger_id}
    follows = [{'timestamp': 3500 + i * 2500, 'abilityGameID': ability}
               for i, (ability, name) in enumerate(list(NAMES.items())[1:])
               if name not in missing]
    rows = [PldFollowUp(name, int(name not in missing),
                       int(name not in missing and name not in no_hit), 100)
            for name in list(NAMES.values())[1:]]
    return follow_up_issues(trigger, follows, rows, NAMES, ready, buffs, life, 7,
                            0, end, end if finish is None else finish,
                            TargetableTime(None, 'recorded', intervals), failures)


def test_missing_actions_with_same_death_context_are_grouped():
    result = issues(life=[{'timestamp': 7000, 'type': 'death', 'targetID': 7}])
    assert len(result) == 1
    assert result[0].actions == ('Blade of Truth', 'Blade of Valor')
    assert result[0].reason == 'death'


@pytest.mark.parametrize('death', [700, 35000])
def test_death_outside_ready_window_does_not_explain_missing_actions(death):
    assert issues(life=[{'timestamp': death, 'type': 'death', 'targetID': 7}])[0].reason == 'unconfirmed'


def test_another_players_death_is_not_used():
    assert issues(life=[{'timestamp': 7000, 'type': 'death', 'targetID': 8}])[0].reason == 'unconfirmed'


def test_sustained_downtime_explains_missing_actions():
    assert issues(intervals=((0, 7000), (35000, 60000)))[0].reason == 'downtime'


def test_downtime_already_in_progress_at_trigger_is_supported():
    assert issues(intervals=((0, 500), (35000, 60000)))[0].reason == 'downtime'


def test_short_downtime_with_resumed_combat_is_not_an_explanation():
    assert issues(intervals=((0, 7000), (10000, 60000)))[0].reason == 'unconfirmed'


def test_delayed_follow_up_after_ready_expiry_does_not_inherit_earlier_downtime():
    result = follow_up_issues(
        {'timestamp': 1000, 'abilityGameID': 1},
        [{'timestamp': 3500, 'abilityGameID': 2},
         {'timestamp': 34000, 'abilityGameID': 3}],
        [PldFollowUp('Blade of Truth', 0, 0, 0)], NAMES, [], [], [], 7, 0, 60000, 60000,
        TargetableTime(None, 'recorded', ((0, 7000), (35000, 60000))),
    )
    assert result[0].reason == 'unconfirmed'


def test_missing_casts_near_fight_end_keep_fight_end_context():
    assert issues(end=10000)[0].reason == 'fight_end'


def test_fight_ending_long_after_ready_window_is_not_an_explanation():
    assert issues(end=60000)[0].reason == 'unconfirmed'


def test_next_trigger_is_not_reported_as_fight_ending():
    assert issues(end=60000, finish=10000)[0].reason == 'unconfirmed'


def test_ready_expiry_accounts_for_recorded_grant_delay():
    ready = ReadyUse('Requiescat charges', 4, 2, 2, 0, 0, 0, ((31.6, '2 expired'),))
    result = issues(ready=[ready], buffs=[{'type': 'applybuff', 'abilityGameID': 1001368,
                                        'timestamp': 1600}])
    assert result[0].reason == 'expiry'
    assert result[0].effect == 'Requiescat charges'


def test_remaining_ready_effect_is_not_reported_as_expired():
    ready = ReadyUse('Requiescat charges', 4, 2, 0, 0, 0, 2)
    assert issues(ready=[ready])[0].reason == 'unconfirmed'


def test_each_ready_effect_explains_only_its_own_consumers():
    ready = ReadyUse('Blade of Honor', 1, 0, 1, 0, 0, 0, ((31, 'expired'),))
    result = issues(missing=('Blade of Truth', 'Blade of Honor'), ready=[ready])
    assert result[0].actions == ('Blade of Truth',)
    assert result[0].reason == 'unconfirmed'
    assert result[1].actions == ('Blade of Honor',)
    assert result[1].reason == 'expiry'


@pytest.mark.parametrize('reason', ['target defeated before hit landed',
                                  'target became untargetable before hit landed',
                                  'phase HP lock', 'target at 1 HP', 'target at 0 HP',
                                  'player defeated before hit landed', 'fight ending'])
def test_cast_without_hit_reuses_shared_reason(reason):
    result = issues(missing=(), no_hit=('Blade of Truth',),
                    failures={('Blade of Truth', 8.5): reason})
    assert result[0].kind == 'no_hit'
    assert result[0].reason == reason


def test_unexplained_hit_does_not_inherit_unrelated_death_context():
    result = issues(missing=(), no_hit=('Blade of Truth',),
                    life=[{'timestamp': 25000, 'type': 'death', 'targetID': 7}])
    assert result[0].reason == 'unconfirmed'


def test_pre_pull_sequence_is_not_labelled_as_player_failure():
    assert issues(trigger_id=-1)[0].reason == 'prepull'


def test_issue_models_round_trip_as_typed_cache_data():
    from ffxiv_potency.analysis.cache import _decode, _encode
    from ffxiv_potency.analysis.pld.follow_ups import PldFollowUpIssue

    issue = replace(issues()[0], reason='expiry', effect='Requiescat charges')
    assert _decode(_encode(issue), PldFollowUpIssue) == issue
