"""Tests for mch pets behavior."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")



def test_pet_modifier_does_not_require_gauge_scaling(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 0, "endTime": 1000})
    write_json(log / "master-data.json", {"abilities": [{"gameID": 1, "name": "Pet Hit"}]})
    write_json(log / "cast-events.json", [])
    write_json(
        log / "damage-events.json",
        [{"timestamp": 500, "type": "damage", "abilityGameID": 1}],
    )
    actions = tmp_path / "actions.json"
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [
                {
                    "name": "Pet Hit",
                    "type": "Ability",
                    "source_actor": "Automaton Queen",
                    "potency": {"base": 115},
                }
            ],
        },
    )

    result = analyze_saved_fight(log, actions)

    assert result.potency_min == result.potency_max == pytest.approx(102.35)



def test_reconstructs_battery_spent_and_exact_pet_potency(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 1000, "endTime": 10000})
    write_json(
        log / "master-data.json",
        {
            "actors": [{"id": 18, "name": "Player", "type": "Player"}],
            "abilities": [
                {"gameID": 1, "name": "Battery Builder"},
                {"gameID": 2, "name": "Automaton Queen"},
                {"gameID": 3, "name": "Pet Hit"},
            ],
        },
    )
    write_json(
        log / "cast-events.json",
        [
            {"timestamp": 2000, "type": "cast", "packetID": 1, "abilityGameID": 1, "sourceID": 18},
            {"timestamp": 3000, "type": "cast", "packetID": 2, "abilityGameID": 2, "sourceID": 18},
        ],
    )
    write_json(
        log / "damage-events.json",
        [
            {"timestamp": 2100, "type": "damage", "packetID": 1, "abilityGameID": 1, "amount": 100},
            {"timestamp": 4000, "type": "damage", "packetID": 3, "abilityGameID": 3},
        ],
    )
    actions = tmp_path / "actions.json"
    write_json(
        log / "rankings.json",
        {
            "metric": "ndps",
            "rdps": {"data": [{"id": 999999, "name": "Player", "amount": 12222.2}]},
            "dps": {"data": [{"id": 999999, "name": "Player", "amount": 13500.0}]},
            "rankings": {
                "data": [
                    {
                        "roles": {
                            "dps": {
                                "characters": [{"id": 999999, "name": "Player", "amount": 12345.6}]
                            }
                        }
                    }
                ]
            },
        },
    )
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [
                {
                    "name": "Battery Builder",
                    "type": "Weaponskill",
                    "potency": None,
                    "gauge_gains": [
                        {"gauge": "Battery Gauge", "amount": 60, "requires_combo": False}
                    ],
                },
                {
                    "name": "Automaton Queen",
                    "type": "Ability",
                    "potency": None,
                    "deploys_actor": "Automaton Queen",
                },
                {
                    "name": "Pet Hit",
                    "type": "Ability",
                    "source_actor": "Automaton Queen",
                    "potency": {
                        "base": 100,
                        "gauge_scaling": {
                            "gauge": "Battery Gauge",
                            "maximum_potency": 200,
                        },
                    },
                },
            ],
        },
    )

    result = analyze_saved_fight(log, actions)

    assert result.pet_deployments[0].actor == "Automaton Queen"
    assert result.pet_deployments[0].timestamp_seconds == 2
    assert result.pet_deployments[0].gauge_spent == 60
    assert (
        result.pet_deployments[0].potency_min
        == result.pet_deployments[0].potency_max
        == pytest.approx(106.8)
    )
    assert result.potency_min == result.potency_max == pytest.approx(106.8)
    assert result.ndps == 12345.6
    assert result.rdps == 12222.2
    assert result.dps == 13500.0
    old_rankings = json.loads((log / "rankings.json").read_text(encoding="utf-8"))["rankings"]
    write_json(log / "rankings.json", old_rankings)
    assert analyze_saved_fight(log, actions).ndps is None



def test_pet_deployments_separate_potion_adjusted_potency(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 0, "endTime": 10000})
    write_json(
        log / "master-data.json",
        {
            "abilities": [
                {"gameID": 1, "name": "Battery Builder"},
                {"gameID": 2, "name": "Automaton Queen"},
                {"gameID": 3, "name": "Pet Hit"},
            ]
        },
    )
    write_json(
        log / "cast-events.json",
        [
            {"timestamp": 100, "packetID": 1, "abilityGameID": 1},
            {"timestamp": 200, "packetID": 2, "abilityGameID": 2},
            {"timestamp": 3000, "packetID": 4, "abilityGameID": 1},
            {"timestamp": 4000, "packetID": 5, "abilityGameID": 2},
        ],
    )
    write_json(
        log / "damage-events.json",
        [
            {"timestamp": 150, "type": "damage", "packetID": 1, "abilityGameID": 1, "amount": 100},
            {"timestamp": 1000, "type": "damage", "packetID": 3, "abilityGameID": 3},
            {"timestamp": 3500, "type": "damage", "packetID": 4, "abilityGameID": 1, "amount": 100},
            {
                "timestamp": 5000,
                "type": "damage",
                "packetID": 6,
                "abilityGameID": 3,
                "buffs": "1000049.",
            },
        ],
    )
    actions = tmp_path / "actions.json"
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [
                {
                    "name": "Battery Builder",
                    "type": "Weaponskill",
                    "potency": None,
                    "gauge_gains": [{"gauge": "Battery Gauge", "amount": 50}],
                },
                {"name": "Automaton Queen", "type": "Ability", "potency": None},
                {
                    "name": "Pet Hit",
                    "type": "Ability",
                    "source_actor": "Automaton Queen",
                    "potency": {"base": 100},
                },
            ],
        },
    )

    result = analyze_saved_fight(log, actions)

    assert len(result.pet_deployments) == 2
    first, second = result.pet_deployments
    assert first.gauge_spent == second.gauge_spent == 50
    assert first.potency_min == first.potency_max == pytest.approx(89)
    assert second.potency_min == second.potency_max == pytest.approx(89 * 563 / 525)
    assert result.potency_min == pytest.approx(first.potency_min + second.potency_min)

