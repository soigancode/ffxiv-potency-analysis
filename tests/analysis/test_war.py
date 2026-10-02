"""Warrior snapshot boundaries and conditional guaranteed outcomes."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight


def test_tempest_grant_and_expiry_use_snapshots_and_inner_release_is_conditional(tmp_path):
    abilities = {45: "Storm's Eye", 31: "Heavy Swing", 3549: "Fell Cleave", 7387: "Upheaval"}
    casts = [
        {
            "timestamp": time,
            "type": "cast",
            "packetID": packet,
            "abilityGameID": ability,
            "sourceID": 1,
            "targetID": 10,
        }
        for time, packet, ability in [
            (1000, 1, 45),
            (2000, 2, 31),
            (2500, 3, 3549),
            (3000, 4, 7387),
            (3500, 5, 3549),
            (4500, 6, 31),
        ]
    ]
    hits = [
        {
            **cast,
            "timestamp": cast["timestamp"] + 1000,
            "type": "damage",
            "amount": 1000,
            "hitType": 2 if cast["packetID"] in {3, 5} else 1,
            "directHit": cast["packetID"] in {3, 5},
            "bonusPercent": 100 if cast["packetID"] == 1 else 0,
            "buffs": "1002677.1001177." if cast["packetID"] in {3, 4} else "1002677.",
        }
        for cast in casts
    ]
    damage = hits + [
        {**hit, "type": "calculateddamage", "timestamp": cast["timestamp"]}
        for cast, hit in zip(casts, hits, strict=True)
    ]
    data = {
        "fight.json": {
            "id": 1,
            "encounterID": 101,
            "name": "Vamp Fatale",
            "startTime": 0,
            "endTime": 10000,
            "reportStartTime": 1780300800000,
            "friendlyPlayers": [1],
        },
        "master-data.json": {
            "abilities": [{"gameID": id_, "name": name} for id_, name in abilities.items()],
            "actors": [{"id": 1, "name": "Test Warrior", "type": "Player", "subType": "Warrior"}],
        },
        "damage-events.json": damage,
        "cast-events.json": casts,
        "buff-events.json": [
            {
                "timestamp": 1000,
                "type": "applybuff",
                "sourceID": 1,
                "targetID": 1,
                "abilityGameID": 1002677,
                "duration": 3000,
            },
            # Another Warrior's buff cannot extend this player's interval.
            {
                "timestamp": 4000,
                "type": "applybuff",
                "sourceID": 2,
                "targetID": 2,
                "abilityGameID": 1002677,
                "duration": 30000,
            },
        ],
    }
    for filename, contents in data.items():
        (tmp_path / filename).write_text(json.dumps(contents))
    result = analyze_saved_fight(tmp_path, Path("data/jobs/war/7.5/actions.json"), use_cache=False)
    actions = {action.name: action for action in result.actions}
    assert actions["Storm's Eye"].potency_min == 500
    assert actions["Heavy Swing"].potency_min == pytest.approx(240 * 1.1 + 240)
    assert actions["Fell Cleave"].potency_min == pytest.approx(2 * 580 * 1.1)
    assert actions["Upheaval"].potency_min == pytest.approx(420 * 1.1)
    # One naturally critical-direct Fell Cleave remains eligible. Inner Release
    # forces only the other Fell Cleave, not Heavy Swing or Upheaval.
    normal = 500 + 240 * 1.1 + 240 + 420 * 1.1
    natural = 580 * 1.1
    assert result.luck_score == pytest.approx(natural / (normal + natural))
    assert result.critical_gear_baseline == pytest.approx(0.278)

    # Both Fell Cleaves contribute their observed CDH bonus to HB. Only the
    # naturally rolled one contributes to Luck.
    bonus = 1.628 * 1.25 - 1
    direct_factor = (1.132 + 0.040) / 1.132
    forced_bonus = 1.628 * 1.25 * direct_factor - 1
    assert result.hit_bonus == pytest.approx(natural * (bonus + forced_bonus) / (normal + 2 * natural))
    assert result.adjusted_hit_bonus == result.hit_bonus


def test_tempest_warning_counts_aoe_use_once_but_keeps_loss_from_all_hits():
    from ffxiv_potency.analysis.targetability import TargetableTime
    from ffxiv_potency.analysis.war.summary import summarize_war

    result = summarize_war(
        [], [], [{"sourceID": 1, "auras": [{"ability": 1002677}]}], {}, {},
        1, 0, 10000,
        [(3000.0, "Mythril Tempest", value, 1.0) for value in (140.0, 140.0, 140.0, 140.0)]
        + [(4500.0, "Mythril Tempest", 140.0, 1.0)],
        TargetableTime(10, "test", ((0, 10000),)), {},
    )
    assert result.tempest_missing == ((3.0, "Mythril Tempest"), (4.5, "Mythril Tempest"))
    assert result.tempest_lost_potency == pytest.approx(70)
    assert result.total_hits == 5


def test_tempest_application_tolerance_does_not_hide_long_lapse_or_change_uptime():
    from ffxiv_potency.analysis.targetability import TargetableTime
    from ffxiv_potency.analysis.war.summary import summarize_war

    result = summarize_war(
        [], [], [{"sourceID": 1, "auras": [{"ability": 1002677}]}], {}, {},
        1, 0, 12000,
        [(1500, "Attack", 100, 1.0), (8500, "Storm's Eye", 500, 1.0)],
        TargetableTime(12, "test", ((0, 12000),)),
        {1002677: ((0, 1000, 1.1), (2000, 4000, 1.1), (9000, 11000, 1.1))},
    )
    assert result.tempest_missing == ((8.5, "Storm's Eye"),)
    assert result.tempest_lost_potency == pytest.approx(50)
    assert result.tempest_uptime == pytest.approx(5 / 12)
    assert result.tempest_hits == 0
    assert result.total_hits == 2
