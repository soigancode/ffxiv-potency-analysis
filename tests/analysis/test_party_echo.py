"""Fight-specific party roles and the selected player's Echo evidence."""

import pytest

from ffxiv_potency.analysis.echo import (
    echo_status,
    is_non_echo_partition,
    normalize_echo_damage,
)
from ffxiv_potency.analysis.errors import AnalysisError
from ffxiv_potency.analysis.party import party_bonus_percent
from ffxiv_potency.analysis.profiles import _load_combat_profile, _player_main_stat_factor


def test_party_bonus_counts_unique_roles_of_fight_players_only() -> None:
    master = {"actors": [
        {"id": 1, "type": "Player", "subType": "Machinist"},
        {"id": 2, "type": "Player", "subType": "Paladin"},
        {"id": 3, "type": "Player", "subType": "Warrior"},
        {"id": 4, "type": "Player", "subType": "WhiteMage"},
        {"id": 5, "type": "Player", "subType": "Pictomancer"},
        {"id": 6, "type": "Player", "subType": "Viper"},
        {"id": 99, "type": "Player", "subType": "Dragoon"},
        {"id": 100, "type": "Player", "subType": "LimitBreak"},
    ]}
    assert party_bonus_percent({"friendlyPlayers": [1, 2, 3, 4]}, master, 1) == 3
    assert party_bonus_percent({"friendlyPlayers": [1, 2, 3, 4, 5]}, master, 1) == 4
    assert party_bonus_percent({"friendlyPlayers": [1, 2, 3, 4, 5, 6]}, master, 1) == 5
    assert party_bonus_percent({"friendlyPlayers": [1, 2, 3, 4, 100]}, master, 1) == 3
    assert party_bonus_percent({}, master, 1) is None


def test_party_bonus_rejects_unknown_fight_participant() -> None:
    master = {"actors": [
        {"id": 1, "type": "Player", "subType": "Bard"},
        {"id": 2, "type": "Player", "subType": "Unknown"},
    ]}
    with pytest.raises(AnalysisError, match="unknown job 'Unknown'"):
        party_bonus_percent({"friendlyPlayers": [1, 2]}, master, 1)
    with pytest.raises(AnalysisError, match="incomplete or invalid"):
        party_bonus_percent({"friendlyPlayers": [2]}, master, 1)


def test_party_bonus_recalculates_main_stat_potion_and_revival_factors() -> None:
    for bonus, expected in ((3, 6711), (4, 6776), (5, 6841)):
        profile = _load_combat_profile("machinist", party_bonus_percent=bonus)
        assert profile.party_main_stat == expected
        assert profile.potted_main_stat == expected + 541
        before = _player_main_stat_factor(expected, 440, 237)
        after = _player_main_stat_factor(expected + 541, 440, 237)
        assert profile.player_potion_multiplier == pytest.approx(after / before)


def test_echo_uses_selected_player_initial_aura_only() -> None:
    initial = [
        {"sourceID": 18, "auras": [{"ability": 1000042}]},
        {"sourceID": 20, "auras": []},
    ]
    assert echo_status(103, 18, initial) == "observed"
    assert echo_status(103, 20, initial) == "absent"
    assert echo_status(103, 18, None) == "unknown"
    assert echo_status(1085, 18, initial) is None
    assert echo_status(103, 20, [{"sourceID": 18, "auras": [{"ability": 1000042}]}]) == "unknown"
    assert echo_status(1083, 18, initial) == "observed"
    assert echo_status(1084, 20, initial) == "absent"
    assert echo_status(1083, 18, None) == "unknown"
    assert echo_status(103, 18, [
        {"sourceID": 18, "auras": []},
        {"sourceID": 18, "auras": [{"ability": 1000042}]},
    ]) == "absent"


def test_echo_normalizes_damage_fields_without_changing_saved_events() -> None:
    events = [
        {"type": "calculateddamage", "amount": 112, "unmitigatedAmount": 224},
        {"type": "damage", "amount": 112, "unmitigatedAmount": 224,
         "overkill": 56, "multiplier": 1.05, "targetResources": {"hitPoints": 10}},
        {"type": "damage", "amount": 0, "hitType": 10},
    ]
    normalized = normalize_echo_damage(events)
    assert normalized[0]["amount"] == pytest.approx(100)
    assert normalized[0]["unmitigatedAmount"] == pytest.approx(200)
    assert normalized[1]["amount"] == pytest.approx(100)
    assert normalized[1]["overkill"] == pytest.approx(50)
    assert normalized[1]["unmitigatedAmount"] == pytest.approx(200)
    assert normalized[1]["multiplier"] == 1.05
    assert normalized[1]["targetResources"]["hitPoints"] == 10
    assert normalized[2]["amount"] == 0
    assert events[1]["amount"] == 112


@pytest.mark.parametrize("partition,expected", [
    (1, True), (2, True), (7, True), (8, True), (13, False), (14, False), (3, False),
])
def test_non_echo_rankings_establish_zero_echo(partition, expected) -> None:
    rankings = {"rankings": {"data": [{"fightID": 23, "partition": partition}]}}
    assert is_non_echo_partition(23, rankings) is expected
    assert not is_non_echo_partition(24, rankings)
    assert not is_non_echo_partition(23, {})
    rankings["rdps"] = {"data": [{"fightID": 23, "partition": 13}]}
    assert not is_non_echo_partition(23, rankings)
