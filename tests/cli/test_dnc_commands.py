"""Dancer is selectable in job-guide, analysis, comparison, and ranking commands."""

import shutil
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis.models import (
    ActionSummary,
    AnalysisResult,
    DncFinishSummary,
    HitOutcomeSummary,
    PotionSummary,
)
from ffxiv_potency.fflogs.selection import ReportFight, ReportPlayer
from ffxiv_potency.jobguide import SnapshotResult

from .helpers import _write_selected_log, saved_html_report

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("alias", ["dnc", "DNC", "dancer", "DANCER"])
def test_jobguide_accepts_dancer_aliases(tmp_path, monkeypatch, capsys, alias):
    def update(**kwargs):
        assert kwargs["job"] == "dancer" and kwargs["patch"] == "7.56"
        return SnapshotResult(tmp_path / "source.html", tmp_path / "actions.json", 41)

    monkeypatch.setattr(cli, "update_job_guide", update)
    assert cli.main(["jobguide", alias, "--output", str(tmp_path)]) == 0
    assert "Wrote 41 actions:" in capsys.readouterr().out


def test_cli_analyses_and_compares_dancer_reports(tmp_path, monkeypatch, capsys):
    # Real-log calculations are covered by tests/audits/test_dnc_dancing_mad.py.
    # Exercise job selection and the actual HTML writers with prepared results here.
    shutil.copytree(ROOT / "data/jobs/dnc", tmp_path / "data/jobs/dnc")
    logs = tmp_path / "data/logs"
    first = logs / "VWJv7x9DbRa4ktH6/fight-7/source-4"
    second = logs / "6mCVqpY1HN47daLG/fight-10/source-9"
    _write_selected_log(first, 4, "Dancer")
    _write_selected_log(second, 9, "Dancer")
    results = {
        directory: AnalysisResult(
            fight_name="Dancing Mad", encounter_id=1085, source_name=player,
            ndps=None, duration_seconds=60, raw_damage_events=1,
            landed_damage_events=1, matched_damage_events=1,
            potency_min=1200, potency_max=1200,
            actions=(ActionSummary("Technical Step", 0, 0, 0, uses=1),
                     ActionSummary("Technical Finish", 1, 1200, 1200, uses=1)),
            auto_attacks=(), pet_deployments=(),
            hit_outcomes=HitOutcomeSummary(1, 0, 0, 0),
            potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
            dnc_finishes=(DncFinishSummary(5, "Technical Finish", 4, 1, 1200),),
            gear_name="7.55 Relic BiS", gear_source="assumed",
        )
        for directory, player in ((first, "Felix Austed"), (second, "Skye Uwu"))
    }
    analyzed: list[Path] = []

    def analyze(directory: Path, actions_path: Path) -> AnalysisResult:
        assert actions_path == Path("data/jobs/dnc/7.4/actions.json")
        analyzed.append(directory.resolve())
        return results[directory.resolve()]

    def fail_download(*args, **kwargs):
        raise AssertionError("saved Dancer reports should not download data")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "analyze_saved_fight", analyze)
    monkeypatch.setattr(cli, "download_report_events", fail_download)
    assert cli.main(["analyse", str(first)]) == 0
    status = capsys.readouterr().out
    assert "Felix Austed" not in status and "Technical Step" not in status
    output = saved_html_report(status).get_text()
    assert "Felix Austed" in output
    assert "Technical Step:" in output
    assert "Gear: 7.55 Relic BiS (assumed)" in output
    assert (
        cli.main(
            [
                "compare",
                "https://www.fflogs.com/reports/VWJv7x9DbRa4ktH6?fight=7&source=4",
                "https://www.fflogs.com/reports/6mCVqpY1HN47daLG?fight=10&source=9",
            ]
        )
        == 0
    )
    status = capsys.readouterr().out
    assert "Felix Austed" not in status and "Skye Uwu" not in status
    report = saved_html_report(status)
    output = report.get_text()
    assert "Felix Austed" in output and "Skye Uwu" in output
    assert len(report.select(".player-report")) == 2
    assert analyzed == [first, first, second]


@pytest.mark.parametrize("alias", ["dnc", "dancer"])
def test_leaderboard_resolves_dancer_alias(tmp_path, monkeypatch, capsys, alias):
    def lookup(encounter, job, **kwargs):
        assert encounter == 1085 and job == "dancer"
        raise ValueError("Dancer rank lookup reached")

    monkeypatch.setattr(cli, "accessible_ranked_sources", lookup)
    assert cli.main(["fflogs", alias, "dmu", "--output", str(tmp_path)]) == 1
    assert "Dancer rank lookup reached" in capsys.readouterr().err


@pytest.mark.parametrize("suffix", ["", "?fight=7", "?source=4"])
def test_report_selection_accepts_dancer_without_prompt(monkeypatch, suffix):
    from ffxiv_potency.fflogs import ReportReference

    fight = ReportFight(
        7, "Dancing Mad", 1085, 1106, True, (ReportPlayer(4, "Felix Austed", "Dancer"),)
    )
    monkeypatch.setattr(cli, "report_fights", lambda _: (fight,))

    def fail_prompt(*args):
        raise AssertionError("the only supported Dancer must be selected automatically")

    monkeypatch.setattr("builtins.input", fail_prompt)
    assert cli._select_report_reference(
        "https://www.fflogs.com/reports/abc123" + suffix
    ) == ReportReference("abc123", 7, 4)
