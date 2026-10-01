"""Tests for potions behavior."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.profiles import _load_combat_profile, _player_main_stat_factor


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")



def test_player_main_stat_matches_relic_set_damage_and_potion_gain() -> None:
    from math import floor

    before = _player_main_stat_factor(6838, 440, 237)
    after = _player_main_stat_factor(7379, 440, 237)
    assert (before, after) == (3546, 3837)
    assert _load_combat_profile("bard").player_potion_multiplier == pytest.approx(3837 / 3546)
    det = (1000 + floor(140 * (2765 - 440) / 2780)) / 1000
    weapon = floor(440 * 115 / 1000 + 158) / 100
    base = floor(floor(floor(floor(100 * before / 100) * det) * weapon) * 1.2)
    crit_rate = (50 + floor(200 * (3585 - 420) / 2780)) / 1000
    crit_multiplier = (1400 + floor(200 * (3585 - 420) / 2780)) / 1000
    direct_rate = floor(550 * (1823 - 420) / 2780) / 1000
    expected = base * (1 + crit_rate * (crit_multiplier - 1)) * (1 + direct_rate * .25)
    assert expected == pytest.approx(12402.73, abs=.005)



def test_applies_exact_potion_multiplier_to_main_potency(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 0, "endTime": 1000})
    write_json(
        log / "master-data.json",
        {
            "actors": [{"id": 18, "name": "Player", "type": "Player"}],
            "abilities": [
                {"gameID": 1, "name": "Hit"},
                {"gameID": 34603667, "name": "Grade 4 Gemdraught of Dexterity [HQ]"},
            ],
        },
    )
    write_json(
        log / "cast-events.json",
        [
            {
                "timestamp": 100,
                "type": "cast",
                "sourceID": 18,
                "abilityGameID": 34603667,
            }
        ],
    )
    write_json(
        log / "damage-events.json",
        [{"timestamp": 500, "type": "damage", "abilityGameID": 1, "buffs": "1000049."}],
    )
    actions = tmp_path / "actions.json"
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [{"name": "Hit", "type": "Ability", "potency": {"base": 100}}],
        },
    )

    result = analyze_saved_fight(log, actions)

    multiplier = 3837 / 3546
    assert result.potency_min == result.potency_max == pytest.approx(100 * multiplier)
    assert result.potion.uses == 1
    assert result.potion.windows[0].start_seconds == pytest.approx(0.1)
    assert result.potion.windows[0].end_seconds == pytest.approx(1.0)
    assert result.potion.potted_potency_min == result.potion.potted_potency_max == 100
    assert result.potion.gained_potency_min == pytest.approx(100 * (multiplier - 1))



@pytest.mark.parametrize("with_removal", [False, True])
def test_recovers_prepull_potion_window_only_when_buff_seen(
    tmp_path: Path, with_removal: bool
) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 100000, "endTime": 550000})
    write_json(
        log / "master-data.json",
        {
            "actors": [{"id": 18, "name": "Player", "type": "Player"}],
            "abilities": [
                {"gameID": 1, "name": "Hit"},
                {"gameID": 2, "name": "Grade 4 Gemdraught of Dexterity [HQ]"},
            ],
        },
    )
    write_json(
        log / "cast-events.json", [{"timestamp": 494000, "sourceID": 18, "abilityGameID": 2}]
    )
    write_json(
        log / "damage-events.json",
        [
            {"timestamp": timestamp, "type": "damage", "abilityGameID": 1, "buffs": "1000049."}
            for timestamp in (101000, 129000, 130500, 496000, 523000)
        ],
    )
    if with_removal:
        write_json(
            log / "buff-events.json",
            [{"timestamp": 130000, "type": "removebuff", "abilityGameID": 49, "targetID": 18}],
        )
    actions = tmp_path / "actions.json"
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [{"name": "Hit", "type": "Ability", "potency": {"base": 100}}],
        },
    )
    result = analyze_saved_fight(log, actions)
    assert result.potion.uses == 2
    first, second = result.potion.windows
    assert first.inferred
    assert first.start_seconds == (0 if with_removal else None)
    assert first.end_seconds == (30 if with_removal else None)
    assert first.observed_start_seconds == 1
    assert first.observed_end_seconds == 30.5
    assert second.start_seconds == 394
    assert second.end_seconds == 424

