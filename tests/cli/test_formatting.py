"""Tests for formatting behavior."""

import json
from dataclasses import replace
from pathlib import Path

from ffxiv_potency import cli
from ffxiv_potency.analysis import (
    ActionSummary,
    AnalysisResult,
    AutoAttackSummary,
    HitOutcomeSummary,
    MchWildfireSummary,
    PetDeploymentSummary,
    PotionSummary,
    PotionWindow,
)
from ffxiv_potency.analysis.models import (
    BrdApexUseEstimate,
    BrdOutsideExpectedHit,
    BrdPitchHitEstimate,
    BrdPotencyEstimateSummary,
    ConsumableIdentity,
    ReducedDamageHit,
)

from .helpers import _write_selected_log


def test_cli_prints_saved_fight_analysis(monkeypatch, tmp_path: Path, capsys) -> None:
    directory = tmp_path / "source-18"
    _write_selected_log(directory, 18)
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")
    expected = AnalysisResult(
        fight_name="Test Boss",
        encounter_id=1,
        source_name="Test Player",
        ndps=12345.6,
        rdps=12330.4,
        duration_seconds=10,
        raw_damage_events=6,
        landed_damage_events=3,
        matched_damage_events=2,
        potency_min=350,
        potency_max=400,
        actions=(ActionSummary("Drill", 1, 600, 600, uses=1),),
        auto_attacks=(AutoAttackSummary("Shot", 3, 2.672, 2.64, 88, 264),),
        pet_deployments=(PetDeploymentSummary("Queen", 222.2, "Battery", 50),),
        hit_outcomes=HitOutcomeSummary(1, 2, 3, 4),
        potion=PotionSummary(
            3, 100, 100, 7, 7,
            windows=(PotionWindow(-2, 28, inferred=True),),
            item=ConsumableIdentity("Grade 4 Gemdraught of Dexterity [HQ]", recorded=True),
        ),
        food=ConsumableIdentity("Caramel Popcorn [HQ]", recorded=True),
        unmatched=(("Shot", 1),),
        ghosted=(("Chain Saw", 2),),
        luck_score=0.4231,
        adjusted_luck_score=0.4012,
        luck_baseline=0.249754668,
        critical_gear_baseline=0.277,
        direct_gear_baseline=0.288,
        direct_critical_gear_baseline=0.277 * 0.288,
        ghosted_times=(("Chain Saw", (222.2, 12)),),
        ghosted_targets=(("Chain Saw", ((222.2, "Test Boss"), (12, "Test Add"))),),
        ghosted_target_low_hp=(("Chain Saw", ((222.2, 0),)),),
        ghosted_ending_times=(("Chain Saw", ((12, "target defeated before hit landed"),)),),
        reduced_damage_hits=(ReducedDamageHit(222.2, "Iron Jaws", 1, 26097, "Test Boss"),),
        brd_potency_estimates=(
            BrdPotencyEstimateSummary(
                "Apex Arrow", 2, 1, 35,
                apex_uses=(BrdApexUseEstimate(12, 1, 85, (85,)),
                           BrdApexUseEstimate(222.2, 1, 95, (95, 100))),
            ),
            BrdPotencyEstimateSummary(
                "Pitch Perfect", 20, 1, 140, 1,
                (BrdOutsideExpectedHit(31_482, 360, 32_445, 36_948),),
                pitch_uncertain_hits=(BrdPitchHitEstimate(222.2, "3-stack full hit", (), True),),
            ),
        ),
        mch_wildfires=(MchWildfireSummary(14.091, 24.673, 5, 1_288.78),),
    )

    def fake_analyze(saved_directory: Path, actions_path: Path) -> AnalysisResult:
        assert saved_directory == directory
        assert actions_path == actions
        return expected

    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)

    assert cli.main(["analyse", str(directory), "--actions", str(actions)]) == 0
    output = capsys.readouterr().out
    assert output.startswith("\nPlayer:") and output.endswith("\n\n")
    assert ("Fight: Test Boss (1)\nDuration: 00m10s\n"
            "Date: 01/05/2026 (UTC)\nPartition: n/a\nPatch: 7.5\n"
            "Party main-stat bonus: 5% (assumed; older saved fight)\n"
            "Food: Caramel Popcorn [HQ]\n"
            "nDPS: 12,345.6\nrDPS: 12,330.4") in output
    cli._print_analysis(
        replace(expected, played_patch="7.51", patch_source="fight date",
                gear_name="7.4 Savage BiS", gear_source="assumed", actions_since="7.4"),
        directory=directory,
    )
    dated_output = capsys.readouterr().out
    assert "Patch: 7.51 (fight date)\nRanking patch bracket: 7.5\n" in dated_output
    assert "Gear: 7.4 Savage BiS (assumed)" in dated_output
    assert "Played patch:" not in dated_output
    cli._print_analysis(replace(expected, kill=False))
    assert "Fight: Test Boss (1)\nDuration: 00m10s (wipe)\n" in capsys.readouterr().out
    assert "Player: Test Player" in output
    assert "Landed potency: 350-400" in output
    assert "Potency per second: 35.00-40.00" in output
    assert "00m12s: 1 hit, 85 gauge" in output
    assert "03m42s: 1 hit, best estimate 95 gauge (plausible 95–100 gauge)" in output
    assert "Pitch Perfect: 20 hits, 1 hit with ambiguous potency\n" in output
    assert "03m42s: closest fit: 3-stack full hit; outside expected damage" in output
    assert "03m42s Chain Saw on Test Boss (target at 0 HP)" in output
    assert "00m12s Chain Saw on Test Add (target defeated before hit landed)" in output
    assert "03m42s Iron Jaws on Test Boss: 1/26,098 damage (0.0038% potency counted)" in output
    assert output.index("Reduced damage hits:") < output.index("Ghosted damaging casts:")
    assert "estimated 2.672s -> 2.64s weapon delay" in output
    assert "Potency gained: 7" in output
    assert "Window 1: -00m02s–00m28s" in output
    assert "Potions:\n  Uses: 3\n  Item: Grade 4 Gemdraught of Dexterity [HQ]" in output
    assert "inferred" not in output
    assert "03m42s Queen" in output
    assert "00m14s–00m25s: 5/6 landed weaponskills, 1,289 potency" in output
    assert output.index("Wildfire:") < output.index("Pet deployments:")
    assert "Shot: 1" in output
    assert "  00m12s Chain Saw on Test Add (target defeated before hit landed)" in output
    assert output.index("Ghosted damaging casts:") < output.index("Potions:")
    expected_outcomes = """Observed hit outcomes:
  Normal Hit: 1
  Direct Hit: 3
  Direct Hit gear baseline: 28.80%
  Direct Hit rate: 70.00% (+41.20%)
  Critical Hit: 2
  Critical Hit gear baseline: 27.70%
  Critical Hit rate: 60.00% (+32.30%)
  Direct Critical Hit: 4
  Direct Critical Hit gear baseline: 7.98%
  Direct Critical Hit rate: 40.00% (+32.02%)
  Luck baseline: 24.98%
  Luck score: 42.31% (+17.33%)
  Adjusted luck score: 40.12% (+15.14%)"""
    assert expected_outcomes in output
    assert "Drill: 1 use, 1 hit, 600 total potency" in output
    assert "per use" not in output and "per hit" not in output

    cli._print_analysis(replace(expected, party_bonus_percent=3, echo_status="observed"))
    echo_output = capsys.readouterr().out
    assert "Party main-stat bonus: 3%\n" in echo_output
    assert "Echo: 12% (damage normalised by 1.12)\n" in echo_output

    cli._print_analysis(replace(expected, potion=PotionSummary(0, 0, 0, 0, 0)))
    unpotted_output = capsys.readouterr().out
    assert "Potions:" not in unpotted_output
    assert "Potted base potency:" not in unpotted_output
    assert "Observed hit outcomes:" in unpotted_output
    cli._print_analysis(replace(expected, echo_status="absent"))
    assert "Echo: 0%\n" in capsys.readouterr().out



def test_time_format_handles_short_and_long_fights() -> None:
    assert cli._format_duration(181) == "03m01s"
    assert cli._format_duration(761) == "12m41s"



def test_fight_date_uses_report_time_plus_fight_offset_and_handles_missing_date(
    tmp_path: Path,
) -> None:
    fight = tmp_path / "fight.json"
    fight.write_text(json.dumps({
        "reportStartTime": 1777593600000,  # 01/05/26 00:00 UTC.
        "startTime": 24 * 60 * 60 * 1000 + 500,
    }), encoding="utf-8")
    assert cli._fight_date(tmp_path) == "02/05/26"
    fight.write_text('{"startTime": 500}', encoding="utf-8")
    assert cli._fight_date(tmp_path) == "n/a"

