"""Tests for analyse behavior."""

import json
import shutil
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import (
    AnalysisResult,
)
from ffxiv_potency.fflogs import DownloadResult, ReportReference

from .helpers import _write_selected_log


def test_cli_analyses_saved_brd_fight(
    monkeypatch, tmp_path: Path, extract_fight, capsys
) -> None:
    extract_fight("brd_dancing_mad.zip", "7CANHrvwKT6tp2Gx/fight-7/source-2/")
    shutil.copytree(Path(__file__).resolve().parents[2] / "data/jobs/brd",
                    tmp_path / "data/jobs/brd")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["analyse", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "Pitch Perfect" in output
    assert "Apex Arrow" in output
    assert "phase transition" not in output
    variable_section = output.split("Variable potency:", 1)[1].split("\n\n", 1)[0]
    assert "Radiant Encore" not in variable_section
    assert "  Radiant Encore:" in output  # Still counted in the actions summary.



def test_cli_analyze_downloads_missing_fflogs_url(monkeypatch, tmp_path: Path, capsys) -> None:
    url = "https://www.fflogs.com/reports/abc123?fight=9&source=18"
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")
    directory = tmp_path / "abc123" / "fight-9" / "source-18"
    expected = DownloadResult(
        directory=directory,
        fight=directory / "fight.json",
        master_data=directory / "master-data.json",
        damage_events=directory / "damage-events.json",
        cast_events=directory / "cast-events.json",
        rankings=directory / "rankings.json",
        damage_event_count=1,
        cast_event_count=1,
    )

    def fake_download(reference, output_root: Path) -> DownloadResult:
        assert reference.report_code == "abc123"
        assert reference.fight_id == 9
        assert reference.source_id == 18
        assert output_root == tmp_path
        _write_selected_log(directory, 18)
        return expected

    def fake_analyze(saved_directory: Path, actions_path: Path) -> AnalysisResult:
        assert saved_directory == directory
        assert actions_path == actions
        raise ValueError("analysis reached")

    monkeypatch.setattr(cli, "download_report_events", fake_download)
    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)

    assert cli.main(["analyse", url, "--actions", str(actions), "--output", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert f"Saved fight data: {directory}" in output.out
    assert "analysis reached" in output.err



def test_cli_analyze_reuses_complete_download(monkeypatch, tmp_path: Path) -> None:
    url = "https://www.fflogs.com/reports/abc123?fight=9&source=18"
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")
    directory = tmp_path / "abc123" / "fight-9" / "source-18"
    _write_selected_log(directory, 18)

    def fail_download(*args, **kwargs):
        raise AssertionError("complete saved data should not be downloaded again")

    def fake_analyze(saved_directory: Path, actions_path: Path) -> AnalysisResult:
        assert saved_directory == directory
        raise ValueError("analysis reached")

    monkeypatch.setattr(cli, "download_report_events", fail_download)
    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)

    assert cli.main(["analyse", url, "--actions", str(actions), "--output", str(tmp_path)]) == 1



def test_analyse_backfills_targetability_without_redownloading_fight(
    monkeypatch, tmp_path: Path
) -> None:
    url = "https://www.fflogs.com/reports/abc123?fight=9&source=18"
    directory = tmp_path / "abc123/fight-9/source-18"
    _write_selected_log(directory, 18)
    monkeypatch.setenv("FFLOGS_CLIENT_ID", "test-id")
    monkeypatch.setenv("FFLOGS_CLIENT_SECRET", "test-secret")
    calls = []

    def fake_refresh(reference, saved_directory: Path) -> None:
        calls.append((reference.fight_id, saved_directory))
        (saved_directory / "targetability-events.json").write_text("[]", encoding="utf-8")

    def fake_overkills(reference, saved_directory: Path) -> None:
        assert reference.fight_id == 9
        assert saved_directory == directory
        (saved_directory / "encounter-overkill-events.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(cli, "refresh_targetability_events", fake_refresh)
    monkeypatch.setattr(cli, "refresh_encounter_overkill_events", fake_overkills)
    def fake_context(reference, saved_directory: Path) -> None:
        assert reference.fight_id == 9
        fight_path = saved_directory / "fight.json"
        fight = json.loads(fight_path.read_text(encoding="utf-8"))
        fight["friendlyPlayers"] = [18]
        fight_path.write_text(json.dumps(fight), encoding="utf-8")
        (saved_directory / "combatant-info-events.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(cli, "refresh_fight_context", fake_context)
    def fake_status(reference, saved_directory: Path) -> None:
        assert reference.fight_id == 9
        assert saved_directory == directory
        (saved_directory / "debuff-events.json").write_text("[]", encoding="utf-8")
        (saved_directory / "life-events.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(cli, "refresh_player_status_events", fake_status)
    assert cli._resolve_analysis_directory(
        url, tmp_path, include_targetability=True
    ) == directory
    assert cli._resolve_analysis_directory(
        url, tmp_path, include_targetability=True
    ) == directory
    assert calls == [(9, directory)]



def test_mch_lindwurm_ii_saved_fight_backfills_checkpoint_once(monkeypatch, tmp_path: Path) -> None:
    directory = tmp_path / "abc123/fight-23/source-18"
    _write_selected_log(directory, 18)
    fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
    fight.update(encounterID=105, friendlyPlayers=[18])
    (directory / "fight.json").write_text(json.dumps(fight))
    for name in ("combatant-info-events.json", "life-events.json",
                 "revival-buff-events.json"):
        (directory / name).write_text("[]")
    monkeypatch.setenv("FFLOGS_CLIENT_ID", "test")
    monkeypatch.setenv("FFLOGS_CLIENT_SECRET", "secret")
    calls = []

    def backfill(reference, saved):
        calls.append((reference, saved))
        (saved / "checkpoint-context.json").write_text('{"carry":false}')

    monkeypatch.setattr(cli, "refresh_checkpoint_context", backfill)
    url = "https://www.fflogs.com/reports/abc123?fight=23&source=18"
    assert cli._resolve_analysis_directory(url, tmp_path) == directory
    assert cli._resolve_analysis_directory(url, tmp_path) == directory
    assert calls == [(ReportReference("abc123", 23, 18), directory)]



def test_anonymous_report_cache_reconstructs_original_code(tmp_path: Path) -> None:
    reference = ReportReference("a:DNaXrgHGZ8PbCkfL", 22, 4)
    directory = cli._saved_directory(tmp_path, reference)
    assert directory == tmp_path / "a-DNaXrgHGZ8PbCkfL/fight-22/source-4"
    assert cli._reference_from_directory(directory) == reference



def test_cli_uses_installed_actions_when_no_checkout_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli._actions_for_job("bard", None).is_file()
    assert cli._actions_for_job("machinist", None).is_file()



def test_cli_identifies_outdated_actions_and_reinstall_step(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    actions = tmp_path / "data/jobs/mch/7.4/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"job":"machinist","schema_version":2}', encoding="utf-8")

    with pytest.raises(ValueError, match=r"schema version 2.*reinstall the current project"):
        cli._actions_for_job("machinist", None)



def test_cli_selects_actions_from_detected_job(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data/logs/abc/fight-1/source-2"
    _write_selected_log(directory, 2, "Machinist")
    actions = tmp_path / "data/jobs/mch/7.4/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")

    def fake_analyze(saved_directory: Path, actions_path: Path):
        assert saved_directory == directory
        assert actions_path == Path("data/jobs/mch/7.4/actions.json")
        raise ValueError("correct actions selected")

    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)
    assert cli.main(["analyse", str(directory)]) == 1
    assert "correct actions selected" in capsys.readouterr().err

