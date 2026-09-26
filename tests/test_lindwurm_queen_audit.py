"""Selected real events from Lindwurm (104) and Lindwurm II (105).

Encounter 104's final Queen spends 50 Battery. The landed attacks are one
Roller Dash (240), three Arm Punches (120 each), and one Pile Bunker (340).
Crowned Collider never lands before the kill: (240 + 3*120 + 340)*0.89 = 836.6.
Encounter 105's opening Queen spends 60 Battery and lands all finishers:
(5*144 + 408 + 468)*0.89*(563/525) = 1523.2528 (potted).
"""

import json
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.fflogs import analyze_saved_fight


def test_real_lindwurm_final_queen_lands_bunker_but_not_collider(
    tmp_path: Path, machinist_actions: Path, load_audit, capsys: pytest.CaptureFixture[str]
) -> None:
    load_audit("lindwurm_104_queen_audit.json")
    result = analyze_saved_fight(tmp_path, machinist_actions)

    (queen,) = result.pet_deployments
    assert result.encounter_id == 104
    assert queen.gauge_spent == 50
    assert queen.potency_min == queen.potency_max == pytest.approx((240 + 3 * 120 + 340) * 0.89)
    assert queen.missing_finishers == ("Crowned Collider",)
    assert result.unmatched == ()
    cli._print_analysis(result)
    assert (
        "6m29s Automaton Queen: 50 Battery Gauge, 837 total potency (missing Crowned Collider)"
        in capsys.readouterr().out
    )


def test_real_lindwurm_ii_queen_lands_both_finishers(
    tmp_path: Path, machinist_actions: Path, load_audit
) -> None:
    load_audit("lindwurm_105_queen_audit.json")
    result = analyze_saved_fight(tmp_path, machinist_actions)

    (queen,) = result.pet_deployments
    assert result.encounter_id == 105
    assert queen.gauge_spent == 60
    assert (
        queen.potency_min
        == queen.potency_max
        == pytest.approx((5 * 144 + 408 + 468) * 0.89 * 563 / 525)
    )
    assert queen.missing_finishers == ()


def test_real_lindwurm_ii_queen_caps_battery_and_uses_roller_dash(
    tmp_path: Path, machinist_actions: Path, load_audit
) -> None:
    load_audit("lindwurm_105_dash_queen_audit.json")
    result = analyze_saved_fight(tmp_path, machinist_actions)

    (queen,) = result.pet_deployments
    # Five combo hits (10 each), Air Anchor, Chain Saw, Excavator (20 each):
    # 110 Battery gained, capped at 100. The Queen lands Dash, three Punches,
    # Bunker, and Collider, all without a potion.
    assert queen.gauge_spent == 100
    assert (
        queen.potency_min == queen.potency_max == pytest.approx((480 + 3 * 240 + 680 + 780) * 0.89)
    )
    assert queen.missing_finishers == ()


def test_queen_without_either_finisher_reports_both(
    tmp_path: Path, machinist_actions: Path, load_audit, capsys: pytest.CaptureFixture[str]
) -> None:
    # A controlled variant of the real interrupted deployment: Bunker also
    # fails to land, as could happen if the fight ended a little earlier.
    source = load_audit("lindwurm_104_queen_audit.json")
    bunker_id = next(
        item["gameID"]
        for item in source["master_data"]["abilities"]
        if item["name"] == "Pile Bunker"
    )
    damage = [event for event in source["damage_events"] if event.get("abilityGameID") != bunker_id]
    (tmp_path / "damage-events.json").write_text(json.dumps(damage), encoding="utf-8")
    result = analyze_saved_fight(tmp_path, machinist_actions)

    (queen,) = result.pet_deployments
    assert queen.potency_min == queen.potency_max == pytest.approx((240 + 3 * 120) * 0.89)
    assert queen.missing_finishers == ("Pile Bunker", "Crowned Collider")
    cli._print_analysis(result)
    assert "missing Pile Bunker and Crowned Collider" in capsys.readouterr().out
