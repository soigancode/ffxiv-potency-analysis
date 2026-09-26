"""Full FF Logs regression for the multi-phase Dancing Mad ultimate fight.

Source: GaAKTpkz4dLq6Qrb, fight 14, player 14. Damage from a snapshot can
retain Medicated after the potion ends; it must not create another use.
"""

import json
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.fflogs import analyze_saved_fight


def test_dancing_mad_potion_windows_and_phase_regression(
    tmp_path: Path, machinist_actions: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight("dancing_mad_ultimate.zip", "GaAKTpkz4dLq6Qrb/fight-14/source-14/")
    result = analyze_saved_fight(tmp_path, machinist_actions)

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
    assert result.adjusted_luck_score == pytest.approx(0.2691658432)
    assert result.luck_baseline == pytest.approx(0.249754668)
    assert result.critical_gear_baseline == pytest.approx(0.277)
    assert result.direct_gear_baseline == pytest.approx(0.288)
    assert result.direct_critical_gear_baseline == pytest.approx(0.277 * 0.288)
    assert result.luck_score > result.adjusted_luck_score

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
    without_chain = analyze_saved_fight(tmp_path, machinist_actions)
    assert without_chain.luck_score == pytest.approx(result.luck_score)
    assert without_chain.adjusted_luck_score > result.adjusted_luck_score
    assert without_chain.luck_baseline == result.luck_baseline

    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert "  Uses: 5" in output
    assert "average interval" not in output
    assert "longest interval" not in output
