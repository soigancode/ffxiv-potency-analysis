import json
from pathlib import Path

import pytest

from ffxiv_potency.fflogs import AnalysisError, analyze_saved_fight


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_rejects_explicit_older_action_snapshot(tmp_path: Path) -> None:
    write_json(tmp_path / "fight.json", {"startTime": 0, "endTime": 1000})
    write_json(tmp_path / "master-data.json", {"abilities": []})
    write_json(tmp_path / "damage-events.json", [])
    write_json(tmp_path / "cast-events.json", [])
    actions = tmp_path / "actions.json"
    write_json(actions, {"job": "machinist", "patch": "7.5", "actions": []})
    with pytest.raises(AnalysisError, match="only patch 7.55"):
        analyze_saved_fight(tmp_path, actions)


def test_analyzes_only_landed_damage_and_reports_ranges_and_ghosts(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test Boss", "startTime": 1000, "endTime": 11000})
    write_json(
        log / "master-data.json",
        {
            "actors": [{"id": 18, "name": "Player", "type": "Player"}],
            "abilities": [
                {"gameID": 1, "name": "Combo End"},
                {"gameID": 2, "name": "Pet Hit"},
                {"gameID": 3, "name": "Unknown Hit"},
                {"gameID": 4, "name": "Power Up"},
                {"gameID": 8, "name": "Shot"},
            ],
        },
    )
    write_json(
        log / "cast-events.json",
        [
            {"timestamp": 1500, "type": "cast", "packetID": 9, "abilityGameID": 4, "targetID": 50},
            {"timestamp": 2000, "type": "cast", "packetID": 10, "abilityGameID": 1, "targetID": 50},
            {"timestamp": 3000, "type": "cast", "packetID": 11, "abilityGameID": 1, "targetID": 50},
        ],
    )
    landed = {
        "timestamp": 2500,
        "type": "damage",
        "packetID": 10,
        "abilityGameID": 1,
        "targetID": 50,
        "bonusPercent": 50,
    }
    write_json(
        log / "damage-events.json",
        [
            {**landed, "type": "calculateddamage"},
            landed,
            {
                "timestamp": 4000,
                "type": "damage",
                "packetID": 12,
                "abilityGameID": 2,
                "targetID": 50,
            },
            {
                "timestamp": 5000,
                "type": "damage",
                "packetID": 13,
                "abilityGameID": 3,
                "targetID": 50,
            },
            {
                "timestamp": 6000,
                "type": "damage",
                "packetID": 14,
                "abilityGameID": 8,
                "targetID": 50,
            },
            {
                "timestamp": 8640,
                "type": "damage",
                "packetID": 15,
                "abilityGameID": 8,
                "targetID": 50,
            },
            {
                "timestamp": 7000,
                "type": "damage",
                "abilityGameID": 8,
                "targetID": 51,
                "hitType": 10,
                "amount": 0,
            },
            {
                "timestamp": 7500,
                "type": "damage",
                "abilityGameID": 1,
                "targetID": 51,
                "hitType": 10,
                "amount": 0,
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
                    "name": "Combo End",
                    "type": "Weaponskill",
                    "potency": {"base": 100, "combo": {"potency": 300}},
                },
                {
                    "name": "Pet Hit",
                    "type": "Ability",
                    "source_actor": "Automaton Queen",
                    "potency": {
                        "base": 50,
                        "gauge_scaling": {"maximum_potency": 100},
                    },
                },
                {
                    "name": "Power Up",
                    "type": "Ability",
                    "potency": {
                        "modifier": {
                            "bonus": 20,
                            "applies_to": "single-target weaponskills",
                            "maximum_uses": 1,
                        }
                    },
                },
            ],
        },
    )

    result = analyze_saved_fight(log, actions)

    assert result.duration_seconds == 10
    assert result.raw_damage_events == 8
    assert result.landed_damage_events == 5
    assert result.matched_damage_events == 2
    comparable_shot = 80 * 183 / 208 / 1.2
    assert result.potency_min == pytest.approx(364.5 + 2 * comparable_shot)
    assert result.potency_max == pytest.approx(409 + 2 * comparable_shot)
    assert result.pps_min == pytest.approx((364.5 + 2 * comparable_shot) / 10)
    assert result.pps_max == pytest.approx((409 + 2 * comparable_shot) / 10)
    assert result.unmatched == (("Unknown Hit", 1),)
    assert result.auto_attacks[0].name == "Shot"
    assert result.auto_attacks[0].hits == 2
    assert result.auto_attacks[0].weapon_delay_seconds == 2.64
    assert result.auto_attacks[0].potency_per_hit == pytest.approx(comparable_shot)
    assert result.auto_attacks[0].total_potency == pytest.approx(2 * comparable_shot)
    assert result.ghosted == (("Combo End", 1),)
    assert result.ghosted_times == (("Combo End", (2.0,)),)


def test_applies_falloff_to_non_primary_targets(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Adds", "startTime": 0, "endTime": 1000})
    write_json(log / "master-data.json", {"abilities": [{"gameID": 1, "name": "AoE"}]})
    write_json(
        log / "cast-events.json",
        [{"timestamp": 10, "type": "cast", "packetID": 5, "abilityGameID": 1, "targetID": 10}],
    )
    write_json(
        log / "damage-events.json",
        [
            {"timestamp": 20, "type": "damage", "packetID": 5, "abilityGameID": 1, "targetID": 10},
            {"timestamp": 20, "type": "damage", "packetID": 5, "abilityGameID": 1, "targetID": 11},
        ],
    )
    actions = tmp_path / "actions.json"
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [
                {
                    "name": "AoE",
                    "type": "Weaponskill",
                    "potency": {"base": 600, "falloff": {"additional_target_multiplier": 0.5}},
                }
            ],
        },
    )

    result = analyze_saved_fight(log, actions)

    assert result.potency_min == result.potency_max == 900


def test_rejects_auto_attack_interval_that_does_not_match_known_delay(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 0, "endTime": 5000})
    write_json(log / "master-data.json", {"abilities": [{"gameID": 8, "name": "Shot"}]})
    write_json(log / "cast-events.json", [])
    write_json(
        log / "damage-events.json",
        [
            {"timestamp": 1000, "type": "damage", "abilityGameID": 8},
            {"timestamp": 3700, "type": "damage", "abilityGameID": 8},
        ],
    )
    actions = tmp_path / "actions.json"
    write_json(actions, {"job": "machinist", "actions": []})

    with pytest.raises(AnalysisError, match="does not match a known value"):
        analyze_saved_fight(log, actions)


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
            {"timestamp": 2100, "type": "damage", "packetID": 1, "abilityGameID": 1},
            {"timestamp": 4000, "type": "damage", "packetID": 3, "abilityGameID": 3},
        ],
    )
    actions = tmp_path / "actions.json"
    write_json(
        log / "rankings.json",
        {
            "metric": "ndps",
            "rdps": {"data": [{"id": 999999, "name": "Player", "amount": 12222.2}]},
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
            {"timestamp": 150, "type": "damage", "packetID": 1, "abilityGameID": 1},
            {"timestamp": 1000, "type": "damage", "packetID": 3, "abilityGameID": 3},
            {"timestamp": 3500, "type": "damage", "packetID": 4, "abilityGameID": 1},
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


def test_summarizes_all_four_hit_outcomes(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 0, "endTime": 1000})
    write_json(log / "master-data.json", {"abilities": [{"gameID": 1, "name": "Hit"}]})
    write_json(log / "cast-events.json", [])
    write_json(
        log / "damage-events.json",
        [
            {"type": "damage", "abilityGameID": 1, "hitType": 1},
            {"type": "damage", "abilityGameID": 1, "hitType": 2},
            {"type": "damage", "abilityGameID": 1, "hitType": 1, "directHit": True},
            {"type": "damage", "abilityGameID": 1, "hitType": 2, "directHit": True},
        ],
    )
    actions = tmp_path / "actions.json"
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [{"name": "Hit", "type": "Ability", "potency": {"base": 1}}],
        },
    )

    outcomes = analyze_saved_fight(log, actions).hit_outcomes

    assert (outcomes.normal, outcomes.critical, outcomes.direct, outcomes.critical_direct) == (
        1,
        1,
        1,
        1,
    )
    assert outcomes.critical_rate == outcomes.direct_rate == 0.5
    assert outcomes.critical_direct_rate == 0.25


def test_luck_score_weights_potency_and_excludes_guaranteed_outcomes(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.mkdir()
    write_json(log / "fight.json", {"name": "Test", "startTime": 0, "endTime": 1000})
    write_json(
        log / "master-data.json",
        {
            "actors": [{"id": 18, "name": "Player", "type": "Player"}],
            "abilities": [
                {"gameID": 1, "name": "Low"},
                {"gameID": 2, "name": "High"},
                {"gameID": 3, "name": "Full Metal Field"},
                {"gameID": 4, "name": "Wildfire"},
                {"gameID": 5, "name": "Reassemble"},
            ],
        },
    )
    write_json(
        log / "cast-events.json",
        [
            {"timestamp": 1, "sourceID": 18, "abilityGameID": 5, "packetID": 10},
            {"timestamp": 2, "sourceID": 18, "abilityGameID": 1, "packetID": 11},
            {"timestamp": 3, "sourceID": 18, "abilityGameID": 3, "packetID": 12},
            {"timestamp": 4, "sourceID": 18, "abilityGameID": 2, "packetID": 13},
            {"timestamp": 5, "sourceID": 18, "abilityGameID": 1, "packetID": 14},
        ],
    )
    write_json(
        log / "damage-events.json",
        [
            {"type": "damage", "abilityGameID": 1, "packetID": 11, "hitType": 2, "directHit": True},
            {"type": "damage", "abilityGameID": 3, "packetID": 12, "hitType": 2, "directHit": True},
            {"type": "damage", "abilityGameID": 4, "packetID": 15, "hitType": 1},
            {"type": "damage", "abilityGameID": 2, "packetID": 13, "hitType": 2},
            {"type": "damage", "abilityGameID": 1, "packetID": 14, "hitType": 1, "directHit": True},
        ],
    )
    actions = tmp_path / "actions.json"
    write_json(
        actions,
        {
            "job": "machinist",
            "actions": [
                {"name": "Low", "type": "Weaponskill", "potency": {"base": 100}},
                {"name": "High", "type": "Weaponskill", "potency": {"base": 300}},
                {
                    "name": "Full Metal Field",
                    "type": "Weaponskill",
                    "potency": {"base": 1000},
                    "description": ["Delivers a critical direct hit to target."],
                },
                {"name": "Wildfire", "type": "Ability", "potency": {"base": 1000}},
                {
                    "name": "Reassemble",
                    "type": "Ability",
                    "potency": None,
                    "description": ["Guarantees that next weaponskill is a critical direct hit."],
                },
            ],
        },
    )

    result = analyze_saved_fight(log, actions)

    # 3,585 Crit gives 1.627x at level 100. Eligible potency is 300 Crit +
    # 100 DH; forced outcomes and Wildfire do not enter the denominator.
    earned_bonus = 300 * 0.627 + 100 * 0.25
    all_cdh_bonus = 400 * (1.627 * 1.25 - 1)
    assert result.luck_score == pytest.approx(earned_bonus / all_cdh_bonus)


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

    multiplier = 659 / 615
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
