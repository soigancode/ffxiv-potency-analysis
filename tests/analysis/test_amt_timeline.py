"""Only verified AMT combat-time metadata moves the analysis origin."""

import pytest

from ffxiv_potency.analysis.timeline import combat_timeline

FIGHT = {'id': 24, 'encounterID': 4550, 'startTime': 11974486, 'endTime': 12866730}


def test_amt_combat_time_matches_website_origin_without_mutating_metadata():
    fight = {**FIGHT, 'combatTime': 869887}
    effective, offset = combat_timeline(fight)
    assert effective['startTime'] == 11996843
    assert offset == 22.357
    assert (12272761 - effective['startTime']) / 1000 == 275.918
    assert fight['startTime'] == FIGHT['startTime']


@pytest.mark.parametrize('combat', [None, 0, -1, 892245, True, '869887', float('nan'),
                                  float('inf')])
def test_invalid_combat_time_retains_original_timeline(combat):
    fight = {**FIGHT, 'combatTime': combat}
    assert combat_timeline(fight) == (fight, None)


@pytest.mark.parametrize('encounter', [4549, 4551, 1085])
def test_other_encounters_keep_original_timeline_even_with_combat_time(encounter):
    fight = {**FIGHT, 'encounterID': encounter, 'combatTime': 869887}
    assert combat_timeline(fight) == (fight, None)


def test_matching_research_context_supplies_combat_time():
    context = {'fight': {**FIGHT, 'combatTime': 869887}}
    assert combat_timeline(FIGHT, context)[1] == 22.357


@pytest.mark.parametrize('key', ['id', 'encounterID', 'startTime', 'endTime'])
def test_mismatched_research_context_is_not_used(key):
    context = {'fight': {**FIGHT, 'combatTime': 869887, key: FIGHT[key] + 1}}
    assert combat_timeline(FIGHT, context) == (FIGHT, None)


def test_current_fight_metadata_takes_precedence_over_research_context():
    fight = {**FIGHT, 'combatTime': None}
    assert combat_timeline(fight, {'fight': {**FIGHT, 'combatTime': 869887}}) == (fight, None)
