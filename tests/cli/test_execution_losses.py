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
from ffxiv_potency.analysis.pld.combos import PldComboInference, PldComboLoss, PldComboSummary
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
    assert f"  Test effect: {expired} expired" in execution_summary(
        capsys.readouterr().out
    ).splitlines()


@pytest.mark.parametrize("job", ["pld", "war", "machinist", "dancer", "dnc-proc"])
def test_execution_summary_separates_expiry_overwrite_and_remaining(job, capsys):
    cli._print_analysis(result_with_losses(job, expired=1, overwritten=2, remaining=1))
    summary = execution_summary(capsys.readouterr().out)
    assert "  Test effect: 1 expired | 2 overwritten" in summary.splitlines()
    assert "Remaining" not in summary
    cli._print_analysis(result_with_losses(job, remaining=1))
    assert "Test effect" not in execution_summary(capsys.readouterr().out)


@pytest.mark.parametrize("job", ["pld", "machinist", "dancer", "dnc-proc"])
def test_execution_summary_reports_death_without_expiry(job, capsys):
    cli._print_analysis(result_with_losses(job, death_lost=1))
    summary = execution_summary(capsys.readouterr().out)
    assert "  Test effect: 1 lost on death" in summary.splitlines()
    assert "Expired" not in summary


@pytest.mark.parametrize("charges", [1, 3])
def test_inner_release_uses_shared_expiry_wording_and_preserves_charge_detail(charges, capsys):
    result = result_with_losses("war")
    assert result.war is not None
    result = replace(result, war=replace(result.war, unused_expired_charges=charges,
                                        expired_charges=((10, charges),)))
    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert execution_summary(output) == f"  Inner Release: {charges} expired"
    noun = "charge" if charges == 1 else "charges"
    assert f"    00m10s: {charges} unused {noun} expired" in output


def test_bard_repertoire_findings_keep_recorded_uncertainty(capsys):
    result = result_with_losses("bard")
    result = replace(result, execution=ExecutionSummary("bard", (), (), (), (), (10,)))
    cli._print_analysis(result)
    assert execution_summary(capsys.readouterr().out) == (
        "  Repertoire: at least 1 unused stack at 00m10s (Empyreal Arrow confirmed)"
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
        '  Cooldown opportunities (full-duration upper bound):',
        '    Intervene: 21/22 uses',
        '    Unused action: 0/3 uses',
    ]


def test_cooldown_opportunities_preserve_confirmed_findings_and_charge_basis(capsys):
    result = result_with_losses('machinist', expired=1)
    assert result.execution is not None
    result = replace(result, execution=replace(result.execution, cooldowns=(
        CooldownUse('Double Check', 10, 12, 'recorded Blazing Shots'),
    )))
    cli._print_analysis(result)
    assert execution_summary(capsys.readouterr().out).splitlines() == [
        '  Test effect: 1 expired',
        '  Cooldown opportunities (upper bound from recorded Blazing Shots):',
        '    Double Check: 10/12 uses',
    ]


def test_no_opportunities_heading_when_no_shortfalls(capsys):
    result = result_with_losses('pld')
    result = replace(result, execution=ExecutionSummary('paladin', (
        CooldownUse('Intervene', 22, 22), CooldownUse('Unknown maximum', 0, None),
    ), (), (), ()))
    cli._print_analysis(result)
    assert execution_summary(capsys.readouterr().out) == '  No confirmed issues in this log.'


@pytest.mark.parametrize('hits,noun', [(1, 'hit'), (2, 'hits')])
def test_combo_losses_and_atonement_group_preserve_ready_outcomes(capsys, hits, noun):
    result = result_with_losses('pld')
    assert result.pld is not None
    ready = (ReadyUse('Atonement', 29, 28, 0, 1, 0, 0),
             ReadyUse('Supplication', 28, 27, 1, 0, 0, 0),
             ReadyUse('Sepulchre', 27, 26, 0, 0, 0, 1),
             ReadyUse('Divine Might', 29, 28, 0, 0, 0, 1))
    result = replace(result, pld=replace(result.pld, ready=ready,
        combos=PldComboSummary((PldComboLoss('Royal Authority', hits, 260 * hits),), 1)))
    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert f'Combos: {hits} uncomboed {noun}, {260 * hits:,.1f} base potency lost' in output
    assert 'Atonement: 1 overwritten' in execution_summary(output)
    assert 'Supplication: 1 expired' in execution_summary(output)
    section = output.split('Combos, ready effects and spell charges:\n', 1)[1].split(
        'Imperator/Requiescat follow-ups:', 1,
    )[0]
    assert section.index('Combo losses:') < section.index('Atonement sequences:')
    assert section.index('Sepulchre:') < section.index('Other ready effects and spell charges:')
    assert 'Sepulchre: 26/27 grants used | Remaining: 1' in section
    assert 'Unconfirmed combo evidence: 1 landed hit' in section
    assert 'Sepulchre' not in execution_summary(output)


def test_missing_combo_evidence_does_not_become_a_confirmed_issue(capsys):
    result = result_with_losses('pld')
    assert result.pld is not None
    result = replace(result, pld=replace(result.pld, combos=PldComboSummary((), 2)))
    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert execution_summary(output) == '  No confirmed issues in this log.'
    assert 'No confirmed combo losses.' in output
    assert 'Unconfirmed combo evidence: 2 landed hits' in output


def test_inferred_combo_losses_are_labelled_separately(capsys):
    result = result_with_losses('pld')
    assert result.pld is not None
    inferred = (PldComboInference('Riot Blade', 10, False, 170, 160, 8, 'Royal Authority'),
                PldComboInference('Royal Authority', 12, True, 460, 0, 10))
    result = replace(result, pld=replace(result.pld, combos=PldComboSummary((), 0, inferred)))
    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert execution_summary(output).splitlines() == [
        '  No confirmed issues in this log.',
        '  Inferred combo losses: 1 uncomboed hit',
    ]
    assert ('  00m10s Royal Authority -> Riot Blade: 160.0 estimated base potency lost '
            '(uncomboed inferred from normalized damage; combo field unavailable)') in output
    assert ('  00m12s previous GCD unavailable -> Royal Authority: 0.0 estimated base potency lost '
            '(comboed inferred from normalized damage; combo field unavailable)') in output
    assert 'Estimated base loss' not in output
    assert 'Unconfirmed combo evidence:' not in output
