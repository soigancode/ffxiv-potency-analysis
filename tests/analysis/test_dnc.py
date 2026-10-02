"""Dancer buff ownership, snapshots, and random-outcome exclusions."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import AnalysisError, analyze_saved_fight
from ffxiv_potency.analysis.damage import falloff_primary_hits
from ffxiv_potency.analysis.dnc.buffs import dnc_self_buff_windows
from ffxiv_potency.analysis.potency import _direct_potency


def test_finish_damage_uses_previous_strength_and_ignores_synthetic_casts(tmp_path: Path) -> None:
    abilities = {
        16191: "Single Standard Finish",
        16192: "Double Standard Finish",
        16196: "Quadruple Technical Finish",
        33218: "Quadruple Technical Finish",
        15989: "Cascade",
        25792: "Starfall Dance",
        16014: "Improvisation",
        1001821: "Standard Finish",
        1001822: "Technical Finish",
    }
    casts = [
        {
            "timestamp": t,
            "type": "cast",
            "packetID": packet,
            "abilityGameID": ability,
            "sourceID": 1,
            "targetID": 10,
        }
        for t, packet, ability in [
            (1000, 1, 16191),
            (2000, 2, 15989),
            (3000, 3, 16192),
            (4000, 4, 16196),
            (5000, 5, 25792),
            (6000, 6, 16014),
        ]
    ]
    casts.append(
        {**casts[3], "timestamp": 4500, "packetID": 40, "abilityGameID": 33218, "fake": True}
    )
    buffs = [
        {
            "timestamp": t,
            "type": kind,
            "packetID": packet,
            "abilityGameID": status,
            "extraAbilityGameID": ability,
            "sourceID": source,
            "targetID": 1,
            "duration": 60000 if status == 1001821 else 20000,
        }
        for t, kind, packet, status, ability, source in [
            (1000, "applybuff", 1, 1001821, 16191, 1),
            (1900, "applybuff", 90, 1001822, 16196, 2),
            (3000, "refreshbuff", 3, 1001821, 16192, 1),
            (4500, "applybuff", 40, 1001822, 33218, 1),
        ]
    ]
    damage = [
        {
            "timestamp": c["timestamp"] + 500,
            "type": "damage",
            "packetID": c["packetID"],
            "abilityGameID": c["abilityGameID"],
            "sourceID": 1,
            "targetID": 10,
            "amount": 10000,
            "hitType": 2 if c["abilityGameID"] == 25792 else 1,
            "directHit": c["abilityGameID"] == 25792,
            "buffs": b,
        }
        for c, b in zip(
            casts[:5],
            ["", "1001821.1001822.", "1001821.1001822.", "1001821.1001822.", "1001821.1001822."],
        )
    ]
    files = {
        "fight": {
            "id": 1,
            "name": "Dancing Mad",
            "encounterID": 1085,
            "startTime": 0,
            "endTime": 10000,
            "playedPatch": "7.56",
        },
        "master-data": {
            "actors": [{"id": 1, "name": "Dancer", "type": "Player", "subType": "Dancer"}],
            "abilities": [{"gameID": k, "name": v} for k, v in abilities.items()],
        },
        "cast-events": casts,
        "damage-events": damage,
        "buff-events": buffs,
    }
    for name, data in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data))
    result = analyze_saved_fight(tmp_path, Path("data/jobs/dnc/7.4/actions.json"), use_cache=False)
    totals = {a.name: a.potency_min for a in result.actions}
    assert totals["Single Standard Finish"] == 540
    assert totals["Cascade"] == pytest.approx(220 * 1.02)
    assert totals["Double Standard Finish"] == pytest.approx(850 * 1.02)
    assert totals["Quadruple Technical Finish"] == pytest.approx(1300 * 1.05)
    assert totals["Starfall Dance"] == pytest.approx(600 * 1.05**2)
    assert result.luck_score == 0  # Guaranteed Starfall CDH contributes to neither sum.
    assert result.unmatched == result.ghosted == ()
    assert len(result.dnc_finishes) == 3


@pytest.mark.parametrize("bonus,expected", [(None, 120), (0, 120), (57, 280)])
def test_fountain_only_uses_combo_potency_for_positive_bonus(bonus, expected) -> None:
    document = json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())
    action = next(a for a in document["actions"] if a["name"] == "Fountain")
    assert _direct_potency(action, {"bonusPercent": bonus}, is_primary_target=True) == (
        expected,
        expected,
    )


def test_dancer_primary_target_uses_normalized_damage_not_selected_target():
    document = json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())
    actions = {a["name"]: a for a in document["actions"]}
    secondary = {
        "targetID": 10,
        "amount": 5000,
        "hitType": 2,
        "directHit": True,
        "abilityGameID": 15997,
        "multiplier": 1.1,
    }
    primary = {
        "targetID": 11,
        "amount": 7000,
        "hitType": 1,
        "abilityGameID": 15997,
        "multiplier": 1.1,
    }
    assert (
        falloff_primary_hits(
            {(1, 15997): [secondary, primary]}, actions, {15997: "Saber Dance"}, 1.627
        )[(1, 15997)]
        is primary
    )


@pytest.mark.parametrize(
    "source,multiplier,expected", [(1, 1.02, 1.02), (1, 1.05, 1.05), (2, 1.05, None)]
)
def test_pre_pull_finish_strength_and_ownership(source, multiplier, expected):
    document = json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())
    actions = {a["name"]: a for a in document["actions"]}
    combatants = [{"sourceID": 1, "auras": [{"source": source, "ability": 1001821}]}]
    damage = [
        {
            "type": "damage",
            "timestamp": 1000,
            "amount": 1000,
            "buffs": "1001821.",
            "multiplier": multiplier,
        }
    ]
    windows, inferred = dnc_self_buff_windows([], [], {}, actions, 1, 0, 10000, combatants, damage)
    if expected is None:
        assert windows == {} and inferred == ()
    else:
        assert windows == {1001821: ((-1, 10000, expected),)}
        assert inferred == (("Standard Finish", expected),)
    damage[0]["buffs"] = "1001821.1002703."  # Unknown external strength, no matching references.
    if source == 1:
        with pytest.raises(AnalysisError, match="cannot determine pre-pull"):
            dnc_self_buff_windows([], [], {}, actions, 1, 0, 10000, combatants, damage)


def test_finish_at_fight_start_keeps_pre_pull_strength_before_its_refresh():
    document = json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())
    actions = {a["name"]: a for a in document["actions"]}
    cast = {"timestamp": 0, "packetID": 1, "abilityGameID": 16192, "sourceID": 1}
    buff = {
        "timestamp": 0,
        "packetID": 1,
        "type": "refreshbuff",
        "abilityGameID": 1001821,
        "sourceID": 1,
        "targetID": 1,
        "extraAbilityGameID": 16192,
    }
    hit = {
        "timestamp": 500,
        "packetID": 1,
        "abilityGameID": 16192,
        "type": "damage",
        "amount": 1000,
        "buffs": "1001821.",
        "multiplier": 1.02,
    }
    combatants = [{"sourceID": 1, "auras": [{"source": 1, "ability": 1001821}]}]
    windows, inferred = dnc_self_buff_windows(
        [cast], [buff], {16192: "Double Standard Finish"}, actions, 1, 0, 10000, combatants, [hit]
    )
    assert inferred == (("Standard Finish", 1.02),)
    assert windows[1001821] == ((-1, 0, 1.02), (0, 10000, 1.05))


@pytest.mark.parametrize("stable_evidence", [True, False])
def test_pre_pull_strength_skips_incompatible_external_buff_references(stable_evidence):
    document = json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())
    actions = {a["name"]: a for a in document["actions"]}
    combatants = [{"sourceID": 1, "auras": [{"source": 1, "ability": 1001821}]}]
    buff = {
        "timestamp": 5000,
        "packetID": 1,
        "type": "refreshbuff",
        "abilityGameID": 1001821,
        "sourceID": 1,
        "targetID": 1,
        "extraAbilityGameID": 16192,
    }
    damage = [
        {
            "type": "damage",
            "timestamp": time,
            "amount": 1000,
            "buffs": statuses,
            "multiplier": multiplier,
        }
        for time, statuses, multiplier in [
            (1000, "1001821.1002964.", 1.07),
            (6000, "1001821.1002964.", 1.07),
            (7000, "1001821.1002964.", 1.11),
        ]
    ]
    if stable_evidence:
        damage.append(
            {
                "type": "damage",
                "timestamp": 1500,
                "amount": 1000,
                "buffs": "1001821.",
                "multiplier": 1.05,
            }
        )
        windows, inferred = dnc_self_buff_windows(
            [],
            [buff],
            {16192: "Double Standard Finish"},
            actions,
            1,
            0,
            10000,
            combatants,
            damage,
        )
        assert inferred == (("Standard Finish", 1.05),)
        assert windows[1001821] == ((-1, 5000, 1.05), (5000, 10000, 1.05))
    else:
        with pytest.raises(AnalysisError, match="cannot determine pre-pull"):
            dnc_self_buff_windows(
                [],
                [buff],
                {16192: "Double Standard Finish"},
                actions,
                1,
                0,
                10000,
                combatants,
                damage,
            )
