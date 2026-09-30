"""A phase-one pull can prove Battery; a phase-two-only report cannot."""

import json

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.errors import AnalysisError
from ffxiv_potency.analysis.mch.checkpoint import mch_checkpoint_gauges
from ffxiv_potency.analysis.profiles import _PetProfile


def test_mch_checkpoint_carries_landed_battery_after_previous_queen(tmp_path) -> None:
    context = {
        "carry": True, "fightID": 23, "sourceID": 2,
        "previousFight": {"id": 22, "encounterID": 104, "kill": True,
                          "startTime": 1000, "endTime": 9000},
        "casts": [
            {"timestamp": 2000, "sourceID": 2, "packetID": 1, "abilityGameID": 1},
            {"timestamp": 3000, "sourceID": 2, "packetID": 2, "abilityGameID": 2},
            {"timestamp": 4000, "sourceID": 2, "packetID": 3, "abilityGameID": 1},
            {"timestamp": 4500, "sourceID": 2, "packetID": 4, "abilityGameID": 1},
        ],
        "damage": [
            {"timestamp": 2000, "type": "damage", "packetID": 1,
             "abilityGameID": 1, "amount": 100},
            {"timestamp": 4000, "type": "damage", "packetID": 3,
             "abilityGameID": 1, "amount": 100},
            {"timestamp": 4500, "type": "damage", "packetID": 4,
             "abilityGameID": 1, "amount": 0},
        ],
    }
    (tmp_path / "checkpoint-context.json").write_text(json.dumps(context))
    actions = {
        "Battery Builder": {"gauge_gains": [{"gauge": "Battery Gauge", "amount": 60}]},
        "Automaton Queen": {},
    }
    profiles = {"Automaton Queen": _PetProfile(
        0.89, "Battery Gauge", 50, 100, "Automaton Queen",
    )}
    fight = {"id": 23, "startTime": 10000}
    assert mch_checkpoint_gauges(tmp_path, fight, 2, actions,
                                 {1: "Battery Builder", 2: "Automaton Queen"}, profiles) == (
        {"Battery Gauge": 60}, False,
    )

    # The post-deployment gain can resolve even if its damage ghosts.
    context["damage"][1].update(type="calculateddamage", unpaired=True)
    (tmp_path / "checkpoint-context.json").write_text(json.dumps(context))
    assert mch_checkpoint_gauges(tmp_path, fight, 2, actions,
                                 {1: "Battery Builder", 2: "Automaton Queen"}, profiles) == (
        {"Battery Gauge": 60}, False,
    )

    context["damage"] = []
    (tmp_path / "checkpoint-context.json").write_text(json.dumps(context))
    assert mch_checkpoint_gauges(tmp_path, fight, 2, actions,
                                 {1: "Battery Builder", 2: "Automaton Queen"}, profiles) == (
        {}, True,
    )

    context["previousFight"]["kill"] = False
    (tmp_path / "checkpoint-context.json").write_text(json.dumps(context))
    with pytest.raises(AnalysisError, match="invalid Lindwurm II checkpoint context"):
        mch_checkpoint_gauges(tmp_path, fight, 2, actions,
                              {1: "Battery Builder", 2: "Automaton Queen"}, profiles)


def test_mch_checkpoint_battery_is_used_for_first_phase_two_queen(tmp_path) -> None:
    def save(name, value):
        (tmp_path / name).write_text(json.dumps(value))

    save("fight.json", {"id": 23, "encounterID": 105, "name": "Lindwurm II",
                        "startTime": 10000, "endTime": 20000})
    save("master-data.json", {"actors": [
        {"id": 18, "name": "Machinist", "type": "Player", "subType": "Machinist"},
        {"id": 19, "name": "Automaton Queen", "type": "Pet", "petOwner": 18},
    ], "abilities": [
        {"gameID": 1, "name": "Air Anchor"},
        {"gameID": 2, "name": "Automaton Queen"},
        {"gameID": 3, "name": "Arm Punch"},
    ]})
    save("cast-events.json", [
        {"timestamp": 10100, "sourceID": 18, "packetID": 10, "abilityGameID": 2},
    ])
    save("damage-events.json", [
        {"timestamp": 12000, "sourceID": 19, "packetID": 11,
         "abilityGameID": 3, "type": "damage", "amount": 5000},
    ])
    save("checkpoint-context.json", {
        "carry": True, "fightID": 23, "sourceID": 18,
        "previousFight": {"id": 22, "encounterID": 104, "kill": True,
                          "startTime": 1000, "endTime": 9000},
        "casts": [
            {"timestamp": 2000 + i * 1000, "sourceID": 18,
             "packetID": i + 1, "abilityGameID": 1} for i in range(3)
        ],
        "damage": [
            {"timestamp": 2000 + i * 1000, "packetID": i + 1,
             "abilityGameID": 1, "type": "damage", "amount": 100} for i in range(3)
        ],
    })
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps({"job": "machinist", "actions": [
        {"name": "Air Anchor", "type": "Weaponskill", "potency": {"base": 600},
         "gauge_gains": [{"gauge": "Battery Gauge", "amount": 20}]},
        {"name": "Automaton Queen", "type": "Ability", "potency": None,
         "deploys_actor": "Automaton Queen"},
        {"name": "Arm Punch", "type": "Ability", "source_actor": "Automaton Queen",
         "potency": {"base": 115}},
    ]}))

    result = analyze_saved_fight(tmp_path, actions)
    assert len(result.pet_deployments) == 1
    assert result.pet_deployments[0].gauge_spent == 60
    assert result.pet_deployments[0].gauge_assumed is False

    save("checkpoint-context.json", {"carry": "unknown"})
    assumed = analyze_saved_fight(tmp_path, actions).pet_deployments[0]
    assert assumed.gauge_spent == 100 and assumed.gauge_assumed is True

    save("checkpoint-context.json", {"carry": False})
    with pytest.raises(AnalysisError, match="reconstructed only 0 Battery Gauge"):
        analyze_saved_fight(tmp_path, actions)
