import json
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.fflogs import (
    ActionSummary,
    AnalysisResult,
    AutoAttackSummary,
    DownloadResult,
    HitOutcomeSummary,
    PetDeploymentSummary,
    PotionSummary,
    PotionWindow,
)
from ffxiv_potency.jobguide import SnapshotResult


def _write_selected_log(directory: Path, source_id: int, subtype: str = "Machinist") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "master-data.json").write_text(
        json.dumps(
            {
                "actors": [{"id": source_id, "type": "Player", "subType": subtype}],
            }
        ),
        encoding="utf-8",
    )
    for name in ("fight.json", "damage-events.json", "cast-events.json"):
        (directory / name).write_text("{}", encoding="utf-8")
    (directory / "rankings.json").write_text(
        '{"metric":"ndps","rankings":{},"rdps":{}}', encoding="utf-8"
    )


@pytest.mark.parametrize("alias", ["machinist", "MACHINIST", "MCH", "mch"])
def test_cli_updates_machinist_snapshot(monkeypatch, tmp_path: Path, capsys, alias: str) -> None:
    expected = SnapshotResult(
        source=tmp_path / "machinist" / "7.55" / "source.html",
        actions=tmp_path / "machinist" / "7.55" / "actions.json",
        action_count=40,
    )

    def fake_update_job_guide(**kwargs) -> SnapshotResult:
        assert kwargs["job"] == "machinist"
        assert kwargs["patch"] == "7.55"
        assert kwargs["output_root"] == tmp_path
        return expected

    monkeypatch.setattr(cli, "update_job_guide", fake_update_job_guide)

    exit_code = cli.main(["jobguide", alias, "--output", str(tmp_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"Saved source: {expected.source}" in output
    assert f"Wrote 40 actions: {expected.actions}" in output


def test_cli_updates_raid_buffs_without_patch(monkeypatch, tmp_path: Path, capsys) -> None:
    expected = tmp_path / "raid_buffs/7.55/effects.json"

    def fake_update(output_root: Path) -> Path:
        assert output_root == tmp_path
        return expected

    monkeypatch.setattr(cli, "update_raid_effects", fake_update)
    assert cli.main(["jobguide", "BUFFS", "--output", str(tmp_path)]) == 0
    assert str(expected) in capsys.readouterr().out


def test_cli_accepts_copied_fflogs_url(monkeypatch, tmp_path: Path, capsys) -> None:
    url = "https://www.fflogs.com/reports/abc123?fight=9&type=damage-done&source=18"
    directory = tmp_path / "abc123" / "fight-9" / "source-18"
    expected = DownloadResult(
        directory=directory,
        fight=directory / "fight.json",
        master_data=directory / "master-data.json",
        damage_events=directory / "damage-events.json",
        cast_events=directory / "cast-events.json",
        rankings=directory / "rankings.json",
        damage_event_count=20,
        cast_event_count=10,
    )

    def fake_download(reference, output_root: Path) -> DownloadResult:
        assert reference.report_code == "abc123"
        assert reference.fight_id == 9
        assert reference.source_id == 18
        assert output_root == tmp_path
        return expected

    monkeypatch.setattr(cli, "download_report_events", fake_download)

    assert cli.main(["fflogs", url, "--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert f"Saved fight data: {directory}" in output
    assert "Damage events: 20" in output
    assert "Cast events: 10" in output


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
        potion=PotionSummary(3, 100, 100, 7, 7, windows=(PotionWindow(-2, 28, inferred=True),)),
        unmatched=(("Shot", 1),),
        ghosted=(("Chain Saw", 2),),
        luck_score=0.4231,
        adjusted_luck_score=0.4012,
        luck_baseline=0.249754668,
        critical_gear_baseline=0.277,
        direct_gear_baseline=0.288,
        direct_critical_gear_baseline=0.277 * 0.288,
        ghosted_times=(("Chain Saw", (222.2, 12)),),
    )

    def fake_analyze(saved_directory: Path, actions_path: Path) -> AnalysisResult:
        assert saved_directory == directory
        assert actions_path == actions
        return expected

    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)

    assert cli.main(["analyse", str(directory), "--actions", str(actions)]) == 0
    output = capsys.readouterr().out
    assert output.startswith("\nPlayer:") and output.endswith("\n\n")
    assert "Fight: Test Boss (1), 0m10s\nnDPS: 12,345.6\nrDPS: 12,330.4" in output
    assert "Player: Test Player" in output
    assert "Landed potency: 350-400" in output
    assert "Potency per second: 35.00-40.00" in output
    assert "estimated 2.672s -> 2.64s weapon delay" in output
    assert "Potency gained: 7" in output
    assert "Window 1: -0m02s–0m28s" in output
    assert "inferred" not in output
    assert "3m42s Queen" in output
    assert "Shot: 1" in output
    assert "  0m12s Chain Saw\n  3m42s Chain Saw" in output
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
  Adjusted luck score: 40.12%"""
    assert expected_outcomes in output
    assert "Drill: 1 use, 1 hit, 600 total potency" in output
    assert "per use" not in output and "per hit" not in output


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


def test_saved_fight_refreshes_old_rankings_only(monkeypatch, tmp_path: Path) -> None:
    url = "https://www.fflogs.com/reports/abc123?fight=9&source=18"
    directory = tmp_path / "abc123/fight-9/source-18"
    _write_selected_log(directory, 18)
    (directory / "rankings.json").write_text('{"data": []}', encoding="utf-8")
    refreshes = 0

    def fake_refresh(reference, saved_directory: Path) -> None:
        nonlocal refreshes
        refreshes += 1
        assert (reference.report_code, reference.fight_id, reference.source_id) == ("abc123", 9, 18)
        assert saved_directory == directory
        (directory / "rankings.json").write_text(
            '{"metric":"ndps","rankings":{"data":[]},"rdps":{}}', encoding="utf-8"
        )

    def fail_download(*args, **kwargs):
        raise AssertionError("existing fight events must be reused")

    monkeypatch.setattr(cli, "refresh_report_rankings", fake_refresh)
    monkeypatch.setattr(cli, "download_report_events", fail_download)
    assert cli._resolve_analysis_directory(url, tmp_path) == directory
    assert cli._resolve_analysis_directory(url, tmp_path) == directory
    assert refreshes == 1


def test_cli_downloads_and_compares_sources(monkeypatch, tmp_path: Path, capsys) -> None:
    urls = [
        "https://www.fflogs.com/reports/abc123?fight=9&source=18",
        "https://www.fflogs.com/reports/def456?fight=2&source=7",
    ]
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")

    def fake_download(reference, output_root: Path) -> DownloadResult:
        directory = (
            output_root
            / reference.report_code
            / f"fight-{reference.fight_id}"
            / f"source-{reference.source_id}"
        )
        _write_selected_log(directory, reference.source_id)
        return DownloadResult(
            directory=directory,
            fight=directory / "fight.json",
            master_data=directory / "master-data.json",
            damage_events=directory / "damage-events.json",
            cast_events=directory / "cast-events.json",
            rankings=directory / "rankings.json",
            damage_event_count=1,
            cast_event_count=1,
        )

    def fake_analyze(directory: Path, actions_path: Path) -> AnalysisResult:
        assert actions_path == actions
        player = "Alice" if "abc123" in str(directory) else "Bob"
        potency = 1000 if player == "Alice" else 1200
        return AnalysisResult(
            fight_name="Boss",
            encounter_id=10,
            source_name=player,
            ndps=15000 if player == "Alice" else 14900,
            rdps=15100 if player == "Alice" else 14950,
            duration_seconds=100,
            raw_damage_events=1,
            landed_damage_events=1,
            matched_damage_events=1,
            potency_min=potency,
            potency_max=potency,
            actions=(),
            auto_attacks=(),
            pet_deployments=(),
            hit_outcomes=HitOutcomeSummary(1, 0, 0, 0),
            potion=PotionSummary(0, 0, 0, 0, 0),
            unmatched=(),
            ghosted=(),
            luck_score=0.5154,
            adjusted_luck_score=0.4512,
        )

    monkeypatch.setattr(cli, "download_report_events", fake_download)
    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)

    assert cli.main(["compare", *urls, "--actions", str(actions), "--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert output.startswith("\nFight:") and output.endswith("\n\n")
    assert "Saved fight data:" not in output
    assert "Fight: Boss (10)" in output
    assert "1m40s" in output
    assert "nDPS" in output and "15,000.0" in output
    assert "rDPS" in output and "15,100.0" in output
    assert "Player" in output and "Luck" in output and "51.54%" in output
    assert "aLuck" in output and "45.12%" in output
    assert "Crit" not in output and "DH" not in output and "CDH" not in output
    assert "Alice" in output and "1,000" in output and "10" in output
    assert "Bob" in output and "1,200" in output and "12" in output

    def fail_download(*args, **kwargs):
        raise AssertionError("complete compare sources should be reused")

    monkeypatch.setattr(cli, "download_report_events", fail_download)
    assert cli.main(["compare", *urls, "--actions", str(actions), "--output", str(tmp_path)]) == 0
    assert "Saved fight data:" not in capsys.readouterr().out


@pytest.mark.parametrize("count", [1, 11])
def test_cli_compare_requires_two_to_ten_urls(capsys, count: int) -> None:
    url = "https://www.fflogs.com/reports/abc?fight=1&source=2"

    assert cli.main(["compare", *([url] * count), "--actions", "actions.json"]) == 1
    assert "compare requires two to ten" in capsys.readouterr().err


def test_cli_compare_accepts_ten_urls(monkeypatch, tmp_path: Path) -> None:
    url = "https://www.fflogs.com/reports/abc?fight=1&source=2"

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        assert source == url and announce is False
        return tmp_path / "source-2"

    def fake_compare(directories, override) -> None:
        assert directories == [tmp_path / "source-2"] * 10
        assert override is None

    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    assert cli.main(["compare", *([url] * 10)]) == 0


def test_cli_default_actions_must_exist_before_compare(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _write_selected_log(tmp_path / "data/logs/abc/fight-1/source-2", 2)
    _write_selected_log(tmp_path / "data/logs/def/fight-1/source-3", 3)
    urls = [
        "https://www.fflogs.com/reports/abc?fight=1&source=2",
        "https://www.fflogs.com/reports/def?fight=1&source=3",
    ]

    assert cli.main(["compare", *urls]) == 1
    error = capsys.readouterr().err
    assert "data/machinist/7.55/actions.json" in error
    assert "jobguide machinist" in error


def test_cli_selects_actions_from_detected_job(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "data/logs/abc/fight-1/source-2"
    _write_selected_log(directory, 2, "Machinist")
    actions = tmp_path / "data/machinist/7.55/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")

    def fake_analyze(saved_directory: Path, actions_path: Path):
        assert saved_directory == directory
        assert actions_path == Path("data/machinist/7.55/actions.json")
        raise ValueError("correct actions selected")

    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)
    assert cli.main(["analyse", str(directory)]) == 1
    assert "correct actions selected" in capsys.readouterr().err


def test_cli_compare_rejects_different_player_jobs(monkeypatch, tmp_path: Path, capsys) -> None:
    _write_selected_log(tmp_path / "abc/fight-1/source-2", 2, "Machinist")
    _write_selected_log(tmp_path / "def/fight-1/source-3", 3, "Bard")

    def fail_download(*args, **kwargs):
        raise AssertionError("sources already exist")

    monkeypatch.setattr(cli, "download_report_events", fail_download)
    urls = [
        "https://www.fflogs.com/reports/abc?fight=1&source=2",
        "https://www.fflogs.com/reports/def?fight=1&source=3",
    ]
    assert cli.main(["compare", *urls, "--output", str(tmp_path)]) == 1
    assert "comparison requires the same job; received: machinist, bard" in capsys.readouterr().err


def test_cli_compare_rejects_different_encounters(monkeypatch, tmp_path: Path, capsys) -> None:
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")

    def fake_download(reference, output_root: Path) -> DownloadResult:
        directory = (
            output_root
            / reference.report_code
            / f"fight-{reference.fight_id}"
            / f"source-{reference.source_id}"
        )
        _write_selected_log(directory, reference.source_id)
        return DownloadResult(
            directory=directory,
            fight=directory / "fight.json",
            master_data=directory / "master-data.json",
            damage_events=directory / "damage-events.json",
            cast_events=directory / "cast-events.json",
            rankings=directory / "rankings.json",
            damage_event_count=0,
            cast_event_count=0,
        )

    def fake_analyze(directory: Path, actions_path: Path) -> AnalysisResult:
        first = "abc" in str(directory)
        return AnalysisResult(
            fight_name="Boss A" if first else "Boss B",
            encounter_id=1 if first else 2,
            source_name="Player",
            ndps=None,
            duration_seconds=1,
            raw_damage_events=0,
            landed_damage_events=0,
            matched_damage_events=0,
            potency_min=0,
            potency_max=0,
            actions=(),
            auto_attacks=(),
            pet_deployments=(),
            hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
            potion=PotionSummary(0, 0, 0, 0, 0),
            unmatched=(),
            ghosted=(),
        )

    monkeypatch.setattr(cli, "download_report_events", fake_download)
    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)
    urls = [
        "https://www.fflogs.com/reports/abc?fight=1&source=2",
        "https://www.fflogs.com/reports/def?fight=1&source=3",
    ]

    assert cli.main(["compare", *urls, "--actions", str(actions), "--output", str(tmp_path)]) == 1
    assert "comparison requires the same fight" in capsys.readouterr().err


@pytest.mark.parametrize(
    "fight, encounter",
    [
        ("m9s", 101),
        ("M10S", 102),
        ("m11s", 103),
        ("m12sp1", 104),
        ("m12sp2", 105),
        ("umad", 1085),
        ("dmu", 1085),
    ],
)
def test_cli_rankings_shortcuts_compare_top_logs(
    monkeypatch, tmp_path: Path, capsys, fight: str, encounter: int
) -> None:
    from ffxiv_potency.fflogs import ReportReference

    seen = []

    def fake_rankings(encounter_id: int, job: str):
        assert (encounter_id, job) == (encounter, "machinist")
        return (ReportReference("abc123", 9, 18), ReportReference("def456", 4, 7))

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        assert output == tmp_path and announce is False
        seen.append(source)
        return tmp_path / str(len(seen))

    def fake_compare(directories, override) -> None:
        assert directories == [tmp_path / "1", tmp_path / "2"]
        assert override is None
        print("Fight: Test Boss (101)")

    monkeypatch.setattr(cli, "top_ranked_sources", fake_rankings)
    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    assert cli.main(["fflogs", "MCH", fight, "--output", str(tmp_path)]) == 0
    assert "Fight: Test Boss (101)" in capsys.readouterr().out
    assert "abc123?fight=9&source=18" in seen[0]
    assert "def456?fight=4&source=7" in seen[1]


def test_progress_reuses_one_line_and_clears_it(monkeypatch, tmp_path: Path) -> None:
    import io

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal = Terminal()
    monkeypatch.setattr(cli.sys, "stderr", terminal)

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        assert not announce
        return tmp_path / source

    def fake_compare(directories, actions, progress) -> None:
        assert directories == [tmp_path / "first", tmp_path / "second"]
        progress.update("Calculating", 0, 2)
        progress.update("Calculating", 1, 2)
        progress.update("Calculating", 2, 2)
        progress.clear()

    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    with cli._Progress() as progress:
        progress.message("Processing...")
        cli._download_and_compare(["first", "second"], tmp_path, None, progress)

    output = terminal.getvalue()
    assert output.startswith("\rProcessing...")
    assert "Downloading: [--------------------] 0/2" in output
    assert "Downloading: [####################] 2/2" in output
    assert "Calculating: [####################] 2/2" in output
    assert "\n" not in output
    assert output.endswith("\r")
    assert output.rsplit("\r", 2)[-2].strip() == ""


def test_rankings_show_processing_before_lookup(monkeypatch, tmp_path: Path) -> None:
    import io

    from ffxiv_potency.fflogs import ReportReference

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal = Terminal()
    monkeypatch.setattr(cli.sys, "stderr", terminal)

    def fake_rankings(encounter_id: int, job: str):
        assert terminal.getvalue() == "\rProcessing..."
        return (ReportReference("abc123", 9, 18), ReportReference("def456", 4, 7))

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        return tmp_path / "saved"

    def fake_compare(directories, override, progress) -> None:
        progress.clear()

    monkeypatch.setattr(cli, "top_ranked_sources", fake_rankings)
    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    assert cli.main(["fflogs", "mch", "m10s", "--output", str(tmp_path)]) == 0
    assert "Downloading:" in terminal.getvalue()
    assert terminal.getvalue().endswith("\r")


def test_progress_clears_on_error(monkeypatch) -> None:
    import io

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal = Terminal()
    monkeypatch.setattr(cli.sys, "stderr", terminal)
    with pytest.raises(ValueError, match="download failed"), cli._Progress() as progress:
        progress.update("Downloading", 0, 10)
        raise ValueError("download failed")
    assert terminal.getvalue().rsplit("\r", 2)[-2].strip() == ""


def test_compare_downloads_concurrently_and_keeps_input_order(monkeypatch, tmp_path: Path) -> None:
    from threading import Barrier

    simultaneous = Barrier(3, timeout=3)
    completed = []

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        simultaneous.wait()  # Sequential downloads would fail this test.
        return tmp_path / source

    def fake_compare(directories, override) -> None:
        completed.extend(directories)

    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    with cli._Progress() as progress:
        cli._download_and_compare(["a", "b", "c", "a"], tmp_path, None, progress)
    assert completed == [tmp_path / name for name in ("a", "b", "c", "a")]
