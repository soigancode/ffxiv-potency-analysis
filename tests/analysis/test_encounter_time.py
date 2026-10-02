"""Encounter windows must not depend on one player's attack uptime."""

import pytest

from ffxiv_potency.analysis.targetability import resolve_targetable_time, targetable_intervals

ACTORS = {
    1: {"type": "Player"},
    10: {"type": "NPC", "subType": "Boss"},
    11: {"type": "NPC", "subType": "Boss"},
    12: {"type": "NPC", "petOwner": 1},
}


def hit(time, target=10, instance=1, amount=100):
    return {
        "type": "damage",
        "timestamp": time,
        "sourceID": 1,
        "targetID": target,
        "targetInstance": instance,
        "amount": amount,
    }


def update(time, target, state, instance=1):
    return {
        "type": "targetabilityupdate",
        "timestamp": time,
        "sourceID": target,
        "sourceInstance": instance,
        "targetable": state,
    }


def test_transitions_overlapping_targets_pets_and_repeated_instances():
    hits = [hit(0), hit(2500), hit(20000, 10, 2), hit(20000, 11), hit(10000, 12)]
    events = [
        update(10000, 10, 0),
        update(20000, 10, 1, 2),
        update(30000, 10, 0, 2),
        update(20000, 11, 1),
        update(35000, 11, 0),
        update(10000, 12, 1),
    ]
    assert targetable_intervals(events, hits, [], ACTORS, 0, 40000) == ((0, 10000), (20000, 35000))


def test_attack_gaps_and_player_death_do_not_close_enemy_window():
    hits = [hit(0), hit(30000)]
    events = [{"type": "death", "timestamp": 5000, "targetID": 1}, update(40000, 10, 0)]
    assert targetable_intervals(events, hits, [], ACTORS, 0, 40000) == ((0, 40000),)


def test_dungeon_travel_uses_party_appearances_and_enemy_deaths():
    fight = {"encounterID": 4549, "startTime": 0, "endTime": 40000}
    party = [hit(0), hit(20000, 11)]
    selected = [hit(5000), hit(25000, 11)]
    deaths = [
        {"type": "death", "timestamp": 10000, "targetID": 10},
        {"type": "death", "timestamp": 30000, "targetID": 11},
    ]
    result = resolve_targetable_time(fight, ACTORS, selected, deaths, [], 5, party)
    assert result.seconds == 20
    assert "encounter enemy" in result.source
    assert result.intervals == ((0, 10000), (20000, 30000))


def test_ranking_damage_duration_is_checked_against_targetability():
    fight = {"encounterID": 1085, "startTime": 0, "endTime": 40000}
    events = [update(30000, 10, 0)]
    result = resolve_targetable_time(fight, ACTORS, [hit(0, amount=9000)], events, [], 300)
    assert result.seconds == 30
    assert result.source == "FF Logs DPS duration"
    # Stale or incomplete damage cannot fabricate a three-second denominator.
    invalid = resolve_targetable_time(fight, ACTORS, [hit(0, amount=900)], events, [], 300)
    assert invalid.seconds == 30
    assert "timeline" in invalid.source
    unavailable = resolve_targetable_time(fight, ACTORS, [], [], [], None)
    assert unavailable.seconds is None
    assert "full fight" in unavailable.source


def test_wipe_without_rankings_uses_visible_targetability():
    fight = {"encounterID": 1085, "startTime": 0, "endTime": 40000, "kill": False}
    result = resolve_targetable_time(fight, ACTORS, [hit(0)], [update(30000, 10, 0)], [], None)
    assert result.seconds == pytest.approx(30)
