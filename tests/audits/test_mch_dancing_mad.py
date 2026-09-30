"""Full FF Logs regression for the multi-phase Dancing Mad ultimate fight.

Source: GaAKTpkz4dLq6Qrb, fight 14, player 14. Damage from a snapshot can
retain Medicated after the potion ends; it must not create another use. Three
Detonators and one Queen Overdrive occur in this fight.
"""

import json
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import analyze_saved_fight


def test_dancing_mad_potion_windows_and_phase_regression(
    tmp_path: Path, mch_actions: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight("mch_dancing_mad_ultimate.zip", "GaAKTpkz4dLq6Qrb/fight-14/source-14/")
    result = analyze_saved_fight(tmp_path, mch_actions)

    assert result.encounter_id == 1085
    assert result.duration_seconds == pytest.approx(1108.412)
    assert result.potion.uses == 5
    assert [window.start_seconds for window in result.potion.windows] == pytest.approx(
        [-0.035, 269.456, 539.553, 810.377, 1080.373]
    )
    assert [window.end_seconds for window in result.potion.windows] == pytest.approx(
        [29.965, 300.066, 570.148, 840.982, 1108.412]
    )
    assert len(result.pet_deployments) == 25
    assert result.auto_attacks[0].hits == 373
    assert sum(count for _, count in result.ghosted) == 8
    assert result.unmatched == ()
    # Ghosted combo Clean Shot (+10) and Air Anchor (+20) now increase Queen
    # weights; the final Clean Shot still counts only 2,131/53,907 of its damage.
    assert result.adjusted_luck_score == pytest.approx(0.2696394669353244)
    assert result.luck_baseline == pytest.approx(0.249754668)
    assert result.critical_gear_baseline == pytest.approx(0.277)
    assert result.direct_gear_baseline == pytest.approx(0.288)
    assert result.direct_critical_gear_baseline == pytest.approx(0.277 * 0.288)
    assert result.luck_score > result.adjusted_luck_score

    assert result.source_name == "Katsu Yggvera"
    assert len(result.mch_wildfires) == 10
    assert result.mch_wildfires[0].applied_seconds == pytest.approx(4.784)
    assert result.mch_wildfires[0].detonated_seconds == pytest.approx(14.770)
    early = [use for use in result.mch_wildfires if use.detonated_early]
    assert [round(use.applied_seconds, 3) for use in early] == [365.927, 849.438, 1096.372]
    # Full Metal Field is cast as Wildfire applies at 365.927s and lands at
    # 366.951s; its landed hit contributes the sixth stack.
    assert [use.landed_weaponskills for use in early] == [6, 4, 1]
    assert sum(use.potency for use in result.mch_wildfires) == pytest.approx(
        next(action.potency_min for action in result.actions if action.name == "Wildfire")
    )

    overdriven = [queen for queen in result.pet_deployments if queen.mch_overdrive_seconds is not None]
    assert len(overdriven) == 1
    assert overdriven[0].timestamp_seconds == pytest.approx(1095.079)
    assert overdriven[0].mch_overdrive_seconds == pytest.approx(1103.054)

    # Chain Stratagem is an enemy debuff carried by the affected damage events.
    # Removing its marker raises the reported luck: the observed crits remain,
    # but their increased chance is no longer attributed to the raid effect.
    events_path = tmp_path / "damage-events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    assert any("1001221." in event.get("buffs", "") for event in events)
    for event in events:
        if "buffs" in event:
            event["buffs"] = event["buffs"].replace("1001221.", "")
    events_path.write_text(json.dumps(events), encoding="utf-8")
    without_chain = analyze_saved_fight(tmp_path, mch_actions)
    assert without_chain.luck_score == pytest.approx(result.luck_score)
    assert without_chain.adjusted_luck_score > result.adjusted_luck_score
    assert without_chain.luck_baseline == result.luck_baseline

    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert "  Uses: 5" in output
    assert "average interval" not in output
    assert "longest interval" not in output
    assert output.count("(detonated early)") == 3
    assert "(Queen Overdrive at 18m23s)" in output
