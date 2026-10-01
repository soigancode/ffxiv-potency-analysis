"""Consumable names come from the player's own FF Logs buff application."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.consumables import (
    food_active,
    food_gaps,
    identify_consumable,
    initial_food_aura,
)
from ffxiv_potency.analysis.models import ConsumableIdentity
from ffxiv_potency.cli import _print_analysis


def test_buff_applier_identifies_consumable_and_does_not_guess_from_other_players() -> None:
    names = {100: "Caramel Popcorn [HQ]", 200: "Grade 4 Gemdraught of Dexterity [HQ]"}
    buffs = [
        {"type": "applybuff", "targetID": 2, "abilityGameID": 1000048,
         "extraAbilityGameID": 100},
        {"type": "applybuff", "targetID": 3, "abilityGameID": 1000049,
         "extraAbilityGameID": 200},
    ]

    assert identify_consumable(buffs, [], names, 2, 1000048, "Configured Food") == (
        ConsumableIdentity("Caramel Popcorn [HQ]", recorded=True)
    )
    assert identify_consumable(buffs, [], names, 2, 1000049, "Configured Potion") == (
        ConsumableIdentity("Configured Potion", recorded=False)
    )


def test_dancing_mad_consumables_are_identified_from_saved_api_events(
    tmp_path: Path, extract_fight
) -> None:
    extract_fight("brd_dancing_mad.zip", "7CANHrvwKT6tp2Gx/fight-7/source-2/")
    actions = Path(__file__).parents[2] / "data/jobs/brd/7.4/actions.json"
    result = analyze_saved_fight(tmp_path, actions)

    assert result.food == ConsumableIdentity("Caramel Popcorn [HQ]", recorded=True)
    assert result.potion.item == ConsumableIdentity(
        "Grade 4 Gemdraught of Dexterity [HQ]", recorded=True
    )


def test_food_gap_starts_with_removal_and_ends_at_reapplication() -> None:
    changes = [
        {"timestamp": 88000, "type": "removebuff", "targetID": 2, "abilityGameID": 1000048},
        {"timestamp": 111000, "type": "applybuff", "targetID": 2, "abilityGameID": 1000048},
        {"timestamp": 180000, "type": "removebuff", "targetID": 2, "abilityGameID": 1000048},
        {"timestamp": 90000, "type": "applybuff", "targetID": 3, "abilityGameID": 1000048},
    ]
    gaps = food_gaps(changes, 2, 1000048, 0, 200000)
    assert gaps == ((88000, 111000), (180000, 200000))
    assert food_active(87999, gaps)
    assert not food_active(88000, gaps)
    assert food_active(111000, gaps)


def test_initial_food_aura_and_missing_observation() -> None:
    combatants = [{"sourceID": 2, "auras": [{"ability": 1000048}]}]
    assert initial_food_aura(combatants, 2, 1000048) is True
    assert initial_food_aura([{"sourceID": 2, "auras": []}], 2, 1000048) is False
    assert initial_food_aura([], 2, 1000048) is None
    assert food_gaps([], 2, 1000048, 0, 100, initially_fed=False) == ((0, 100),)
    assert food_gaps([], 2, 1000048, 0, 100, initially_fed=None) == ()
    assert food_gaps([], 2, 1000048, 0, 100, initially_fed=True) == ()
    applied = [{"timestamp": 40, "type": "applybuff", "targetID": 2,
                "abilityGameID": 1000048}]
    assert food_gaps(applied, 2, 1000048, 0, 100, initially_fed=False) == ((0, 40),)


def test_real_food_expiry_changes_luck_baseline_without_changing_landed_potency(
    tmp_path: Path, extract_fight, capsys
) -> None:
    extract_fight("brd_food_expiry.zip", "gBtCvT39QpRF1xWA/fight-8/source-2/")
    actions = Path(__file__).parents[2] / "data/jobs/brd/7.4/actions.json"
    actual = analyze_saved_fight(tmp_path, actions)

    assert actual.food == ConsumableIdentity("Caramel Popcorn [HQ]", recorded=True)
    assert actual.food_missing_windows == ((88.234, 111.731),)
    assert actual.critical_gear_baseline == pytest.approx(0.27640298507462746)
    assert actual.luck_baseline == pytest.approx(0.24631964335202455)
    assert actual.potion.item == ConsumableIdentity(
        "Grade 4 Gemdraught of Dexterity [HQ]", recorded=True
    )

    _print_analysis(actual)
    assert "Without food: 01m28s–01m52s" in capsys.readouterr().out

    buff_path = tmp_path / "buff-events.json"
    buffs = json.loads(buff_path.read_text(encoding="utf-8"))
    buff_path.write_text(
        json.dumps([event for event in buffs if event.get("abilityGameID") != 1000048]),
        encoding="utf-8",
    )
    assumed_fed = analyze_saved_fight(tmp_path, actions)
    assert assumed_fed.food_missing_windows == ()
    assert assumed_fed.critical_gear_baseline == pytest.approx(0.277)
    assert actual.potency_min == pytest.approx(assumed_fed.potency_min)
    assert actual.luck_baseline < assumed_fed.luck_baseline
