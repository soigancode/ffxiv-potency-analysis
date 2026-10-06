"""Tests for formatting behavior."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

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
from ffxiv_potency.analysis.penalties import DamagePenaltySummary, StatusWindow
from ffxiv_potency.analysis.war.summary import WarSummary, WarTomahawk

from .helpers import _write_selected_log


@pytest.mark.parametrize("refreshes,note", [
    ((353.307,), ""),
    ((353.307, 360.1), "    Refreshed: 06m 00s"),
    ((360.1, 360.2), "    Refreshed: 06m 00s"),
])
def test_penalty_refresh_notes_show_distinct_displayed_times(capsys, refreshes, note):
    result = AnalysisResult(
        fight_name="Boss", encounter_id=4550, source_name="Player", ndps=None,
        duration_seconds=400, raw_damage_events=0, landed_damage_events=0,
        matched_damage_events=0, potency_min=0, potency_max=0, actions=(),
        auto_attacks=(), pet_deployments=(), hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
        status_windows=(StatusWindow("Damage Down", 353.262, 383.307, "expired", refreshes),),
        damage_penalties=(DamagePenaltySummary("Damage Down", 0.85, 353.262, 383.307, 0),),
    )
    cli._print_analysis(result)
    output = capsys.readouterr().out
    notes = [line for line in output.splitlines() if "Refreshed:" in line]
    assert notes == ([note] if note else [])
    assert result.status_windows[0].refresh_seconds == refreshes


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
        random_hit_outcomes=HitOutcomeSummary(1, 2, 3, 4),
        potion=PotionSummary(
            3, 100, 100, 7, 7,
            windows=(PotionWindow(-2, 28, inferred=True),),
            item=ConsumableIdentity("Grade 4 Gemdraught of Dexterity [HQ]", recorded=True),
        ),
        food=ConsumableIdentity("Caramel Popcorn [HQ]", recorded=True),
        unmatched=(("Shot", 1),),
        ghosted=(("Chain Saw", 2),),
        hit_bonus=0.48,
        adjusted_hit_bonus=0.45,
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
                pitch_uncertain_hits=(BrdPitchHitEstimate(222.2, "3-stack full hit", (), True, 2.97, 31482, 32445, 36948),),
            ),
        ),
        mch_wildfires=(MchWildfireSummary(14.091, 24.673, 5, 1_288.78, contributing_actions=("Blazing Shot",) * 5),),
    )

    def fake_analyze(saved_directory: Path, actions_path: Path) -> AnalysisResult:
        assert saved_directory == directory
        assert actions_path == actions
        return expected

    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)

    assert cli.main(["analyse", str(directory), "--actions", str(actions)]) == 0
    status = capsys.readouterr().out
    assert status.startswith("Saved HTML report:") and "Player:" not in status
    cli._print_analysis(expected, directory=directory)
    output = capsys.readouterr().out
    assert output.startswith("\nPlayer:") and output.endswith("\n\n")
    lines = output.strip().splitlines()
    assert lines[:4] == [
        "Player: Test Player",
        "Fight: Test Boss | Duration: 00m 10s | Targetable: n/a",
        "Date: 01/05/2026 (UTC) | Patch: 7.5",
        "Gear: custom profile | Food: Caramel Popcorn [HQ]",
    ]
    assert "Landed potency: 350-400 | PPS: 35.00-40.00 | rDPS: 12,330.4 | nDPS: 12,345.6" in output
    assert "Potions:\n  Item: Grade 4 Gemdraught of Dexterity [HQ]\n    Window 1:" in output
    assert "  Potion: Grade 4 Gemdraught of Dexterity [HQ]" not in output
    assert "Window 1: -00m 02s - 00m 28s" in output
    assert "Total base potency: 100 | Potion gain: 7 (+7.00%)" in output
    compact = " ".join(output.split())
    assert "03m 42s Chain Saw Test Boss target at 0 HP" in compact
    assert "00m 12s Chain Saw Test Add target defeated before hit landed" in compact
    assert "03m 42s Iron Jaws Test Boss 0.0038%" in compact
    assert output.index("Wildfire:") < output.index("Automaton Queen and Battery:") < output.index("Potions:")
    assert output.index("Execution summary:") < output.index("Deaths and damage penalties:") < output.index("Cooldowns and burst windows:")
    assert output.index("Potions:") < output.index("Ghosted attacks and reduced hits:") < output.index("Hit Bonus and Luck:") < output.index("Action totals and auto-attacks:") < output.index("  Auto-attacks:") < output.index("Data and assumptions:")
    assert "\nAuto-attacks:" not in output
    assert "Base potency per hit" in output
    assert "Shot 3 2.64s 88.00 264" in " ".join(output.split())
    normalized = " ".join(output.split())
    assert "00m 12s 85 85 1 n/a" in normalized
    assert "03m 42s 95/100 95 1 n/a" in normalized
    assert "03m 42s: best fit 3-stack full hit | Damage: 31,482 | Expected: 32,445-36,948 (3.0% below range)" in output
    assert "    GCDs: " + " -> ".join(["BS"] * 5) in output
    assert "Action totals and auto-attacks:\n  Action" in output
    assert "Difference" in output
    assert "Drill 1 1 600" in normalized
    assert "Outcome Gear baseline Observed Difference Hits" in normalized
    assert "Direct Hit 20.82% 30.00% +9.18 pp 3" in normalized
    assert output.index("Direct Hit") < output.index("Critical Hit")
    assert "Luck 24.98% 42.31% 40.12%" in normalized
    assert "Hit Bonus - +48.00% +45.00%" in normalized
    adjusted_note = "Adjusted values remove the expected benefit of other players' Direct Hit and Critical Hit rate buffs."
    assert output.count(adjusted_note) == 1
    assert output.index("Reconstructed DoT ticks do not record DH or Crit outcomes, so they are excluded from Hit Bonus and Luck.") < output.index(adjusted_note) < output.index("Action totals and auto-attacks:")
    assert "Guaranteed Direct Hits and Critical Hits count toward Hit Bonus, but are excluded from Luck" in output
    cli._print_analysis(replace(expected, played_patch="7.51", patch_source="fight date",
                                gear_name="7.4 Savage BiS", gear_source="assumed", actions_since="7.4"), directory=directory)
    dated = capsys.readouterr().out
    assert "Patch: 7.51" in dated
    assert "Gear: 7.4 Savage BiS (assumed) | Food:" in dated
    assert "Partition: n/a | Ranking patch bracket: 7.5" in dated
    cli._print_analysis(replace(expected, kill=False))
    assert "Duration: 00m 10s (wipe)" in capsys.readouterr().out
    war = WarSummary(1.0, 100.0, 2, 2, (), 0, 1, 3, 0, (), 1,
                     (WarTomahawk(422, "Inner Chaos", 2.54, "Heavy Swing", 3.48, (9.87,)),))
    cli._print_analysis(replace(expected, war=war))
    war_output = capsys.readouterr().out
    assert war_output.index("Cooldowns and burst windows:") < war_output.index("Surging Tempest:") < war_output.index("Melee downtime:")
    assert "Tomahawk: 2 uses in 1 chain" in war_output
    assert "07m 02s: Inner Chaos -> 2.54s -> T -> 9.87s -> T -> 3.48s -> Heavy Swing" in war_output
    assert "  T = Tomahawk." not in war_output
    cli._print_analysis(replace(expected, party_bonus_percent=3, echo_status="observed"))
    echo_output = capsys.readouterr().out
    assert "Party main-stat bonus: 3% (recorded)" in echo_output
    assert "12% damage normalised by 1.12" in echo_output
    cli._print_analysis(replace(expected, potion=PotionSummary(0, 0, 0, 0, 0)))
    unpotted = capsys.readouterr().out
    assert "Potions:" not in unpotted and "Total base potency:" not in unpotted
    assert "Hit Bonus and Luck:" in unpotted
    cli._print_analysis(replace(expected, echo_status="absent"))
    assert "Echo: 0%" in capsys.readouterr().out



def test_time_format_handles_short_and_long_fights() -> None:
    assert cli._format_duration(181) == "03m 01s"
    assert cli._format_duration(761) == "12m 41s"



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


def test_comparison_delta_preserves_uncertainty_and_zero_baseline():
    baseline = AnalysisResult(
        fight_name="Boss", encounter_id=1, source_name="Player", ndps=None,
        duration_seconds=10, raw_damage_events=0, landed_damage_events=0,
        matched_damage_events=0, potency_min=1000, potency_max=1000,
        actions=(), auto_attacks=(), pet_deployments=(),
        hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
    )
    assert cli._format_pps_delta(baseline, baseline, 0) == "-"
    assert cli._format_pps_delta(replace(baseline, potency_min=1100, potency_max=1200), baseline, 1) == "+10.00% to +20.00%"
    assert cli._format_pps_delta(baseline, replace(baseline, potency_min=0), 1) == "n/a"


def test_issue_markers_only_count_confirmed_target_ghosts():
    from ffxiv_potency.analysis.penalties import StatusWindow
    from ffxiv_potency.reporting import issue_notes

    result = AnalysisResult(
        fight_name="Boss", encounter_id=1, source_name="Player", ndps=None,
        duration_seconds=10, raw_damage_events=0, landed_damage_events=0,
        matched_damage_events=0, potency_min=1000, potency_max=1000,
        actions=(), auto_attacks=(), pet_deployments=(),
        hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
    )
    result = replace(result,
        status_windows=(StatusWindow("Dead", 1, 2, "revived"), StatusWindow("Damage Down", 3, 4, "expired")),
        ghosted_ending_times=(("Attack", ((1, "target defeated before hit landed"), (2, "target became untargetable"), (3, "player died"), (4, "target defeated before hit landed"))),),
        ghosted_target_low_hp=(("Attack", ((4, 0),)),),
    )
    assert issue_notes(result) == "KOx1 DDx1 Gx2"


def test_dot_gap_tolerance_is_per_gap_and_does_not_change_uptime():
    from ffxiv_potency.analysis.execution import Coverage
    from ffxiv_potency.reporting import reported_coverage_gaps

    effect = Coverage(
        "Caustic Bite", 95.4, 100,
        ((0, 0.8), (10, 10.3), (20, 20.8), (30, 31), (40, 41.7)),
        first_application_seconds=0.8,
    )
    assert reported_coverage_gaps(effect) == ((40, 41.7),)
    assert effect.covered_seconds == 95.4
    assert len(effect.gaps) == 5
    assert reported_coverage_gaps(replace(effect, name="Stormbite")) == ((40, 41.7),)
    # The tolerance does not hide gaps in songs or other personal buffs.
    assert reported_coverage_gaps(replace(effect, name="Songs")) == effect.avoidable_gaps
