"""Execution-summary loss wording across job-specific result models."""

from dataclasses import replace

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis.execution import CooldownUse, ExecutionSummary, ReadyUse
from ffxiv_potency.analysis.models import (
    AnalysisResult,
    DncProcSummary,
    DncReadyProcSummary,
    HitOutcomeSummary,
    PotionSummary,
)
from ffxiv_potency.analysis.pld.summary import PldDotSummary, PldSummary
from ffxiv_potency.analysis.war.summary import WarReadySummary, WarSummary


def result_with_losses(job, expired=0, overwritten=0, death_lost=0, remaining=0):
    result = AnalysisResult(
        fight_name="Test", encounter_id=1, source_name="Player", ndps=None,
        duration_seconds=60, raw_damage_events=0, landed_damage_events=0,
        matched_damage_events=0, potency_min=0, potency_max=0, actions=(),
        auto_attacks=(), pet_deployments=(), hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
    )
    ready = ReadyUse("Test effect", 5, 0, expired, overwritten, death_lost, remaining)
    if job == "pld":
        return replace(result, pld=PldSummary((ready,), (), (), (), PldDotSummary(0, 0, 0, 0)))
    elif job == "war":
        effect = WarReadySummary("Test effect", 5, 0, expired, overwritten, remaining, 0)
        return replace(result, war=WarSummary(None, None, 0, 0, (), 0, 0, 0, 0, (effect,), 0, ()))
    elif job == "dnc-proc":
        proc = DncReadyProcSummary(
            "Test effect", (), 0, 0, 0, 0, 0, 0, 0, overwritten, expired,
            death_lost, remaining, 0, 0,
        )
        summary = DncProcSummary(
            0, 0, 0, None, None, None, None, 0, 0, None, 0, 0, ready_procs=(proc,),
        )
        return replace(result, dnc_procs=summary)
    return replace(result, execution=ExecutionSummary(job, (), (), (ready,), ()))


def execution_summary(output):
    return output.split("Execution summary:\n", 1)[1].split("\n\n", 1)[0]


@pytest.mark.parametrize("job", ["pld", "war", "machinist", "dancer", "dnc-proc"])
@pytest.mark.parametrize("expired", [1, 3])
def test_execution_summary_uses_shared_expiry_wording(job, expired, capsys):
    cli._print_analysis(result_with_losses(job, expired=expired))
    assert f"  Test effect: Expired: {expired}" in execution_summary(
        capsys.readouterr().out
    ).splitlines()


@pytest.mark.parametrize("job", ["pld", "war", "machinist", "dancer", "dnc-proc"])
def test_execution_summary_separates_expiry_overwrite_and_remaining(job, capsys):
    cli._print_analysis(result_with_losses(job, expired=1, overwritten=2, remaining=1))
    summary = execution_summary(capsys.readouterr().out)
    assert "  Test effect: Expired: 1 | Overwritten: 2" in summary.splitlines()
    assert "Remaining" not in summary
    cli._print_analysis(result_with_losses(job, remaining=1))
    assert "Test effect" not in execution_summary(capsys.readouterr().out)


@pytest.mark.parametrize("job", ["pld", "machinist", "dancer", "dnc-proc"])
def test_execution_summary_reports_death_without_expiry(job, capsys):
    cli._print_analysis(result_with_losses(job, death_lost=1))
    summary = execution_summary(capsys.readouterr().out)
    assert "  Test effect: Lost on death: 1" in summary.splitlines()
    assert "Expired" not in summary


@pytest.mark.parametrize("charges", [1, 3])
def test_inner_release_uses_shared_expiry_wording_and_preserves_charge_detail(charges, capsys):
    result = result_with_losses("war")
    assert result.war is not None
    result = replace(result, war=replace(result.war, unused_expired_charges=charges,
                                        expired_charges=((10, charges),)))
    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert execution_summary(output) == f"  Inner Release: Expired: {charges}"
    noun = "charge" if charges == 1 else "charges"
    assert f"    00m10s: {charges} unused {noun} expired" in output


def test_bard_repertoire_findings_keep_recorded_uncertainty(capsys):
    result = result_with_losses("bard")
    result = replace(result, execution=ExecutionSummary("bard", (), (), (), (), (10,)))
    cli._print_analysis(result)
    assert execution_summary(capsys.readouterr().out) == (
        "  00m10s: at least 1 unused Repertoire stack (Empyreal Arrow confirmed)"
    )


@pytest.mark.parametrize('job', ['pld', 'war', 'bard', 'machinist', 'dancer'])
def test_cooldown_opportunities_are_separate_from_confirmed_issues(job, capsys):
    result = result_with_losses(job)
    result = replace(result, execution=ExecutionSummary(job, (
        CooldownUse('Intervene', 21, 22),
        CooldownUse('Unused action', 0, 3),
        CooldownUse('Fully used', 11, 11),
        CooldownUse('Extra uses', 12, 11),
        CooldownUse('Unknown maximum', 0, None),
    ), (), (), ()))
    cli._print_analysis(result)
    summary = execution_summary(capsys.readouterr().out)
    assert summary.splitlines() == [
        '  No confirmed issues in this log.',
        '  Cooldown opportunities:',
        '    Intervene: 21/22 uses (full-duration upper bound)',
        '    Unused action: 0/3 uses (full-duration upper bound)',
    ]


def test_cooldown_opportunities_preserve_confirmed_findings_and_charge_basis(capsys):
    result = result_with_losses('machinist', expired=1)
    assert result.execution is not None
    result = replace(result, execution=replace(result.execution, cooldowns=(
        CooldownUse('Double Check', 10, 12, 'recorded Blazing Shots'),
    )))
    cli._print_analysis(result)
    assert execution_summary(capsys.readouterr().out).splitlines() == [
        '  Test effect: Expired: 1',
        '  Cooldown opportunities:',
        '    Double Check: 10/12 uses (upper bound from recorded Blazing Shots)',
    ]


def test_no_opportunities_heading_when_no_shortfalls(capsys):
    result = result_with_losses('pld')
    result = replace(result, execution=ExecutionSummary('paladin', (
        CooldownUse('Intervene', 22, 22), CooldownUse('Unknown maximum', 0, None),
    ), (), (), ()))
    cli._print_analysis(result)
    assert execution_summary(capsys.readouterr().out) == '  No confirmed issues in this log.'
