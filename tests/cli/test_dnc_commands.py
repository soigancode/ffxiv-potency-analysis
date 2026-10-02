"""Dancer is selectable in job-guide, analysis, comparison, and ranking commands."""

import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest

from ffxiv_potency import cli
from ffxiv_potency.fflogs.selection import ReportFight, ReportPlayer
from ffxiv_potency.jobguide import SnapshotResult

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("alias", ["dnc", "DNC", "dancer", "DANCER"])
def test_jobguide_accepts_dancer_aliases(tmp_path, monkeypatch, capsys, alias):
    def update(**kwargs):
        assert kwargs["job"] == "dancer" and kwargs["patch"] == "7.56"
        return SnapshotResult(tmp_path / "source.html", tmp_path / "actions.json", 41)

    monkeypatch.setattr(cli, "update_job_guide", update)
    assert cli.main(["jobguide", alias, "--output", str(tmp_path)]) == 0
    assert "Wrote 41 actions:" in capsys.readouterr().out


def test_cli_analyses_and_compares_supplied_dancer_logs(tmp_path, monkeypatch, capsys):
    shutil.copytree(ROOT / "data/jobs/dnc", tmp_path / "data/jobs/dnc")
    logs = tmp_path / "data/logs"
    with ZipFile(ROOT / "tests/fixtures/logs/dnc_dancing_mad.zip") as archive:
        for member in archive.namelist():
            if member.endswith(".json"):
                path = logs / member
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(member))
    monkeypatch.chdir(tmp_path)
    first = logs / "VWJv7x9DbRa4ktH6/fight-7/source-4"
    assert cli.main(["analyse", str(first)]) == 0
    output = capsys.readouterr().out
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
    output = capsys.readouterr().out
    assert "Felix Austed" in output and "Skye Uwu" in output


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
