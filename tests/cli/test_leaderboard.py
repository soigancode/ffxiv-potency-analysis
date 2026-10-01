"""Tests for leaderboard behavior."""

import io
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import (
    AnalysisResult,
    HitOutcomeSummary,
    PotionSummary,
)
from ffxiv_potency.fflogs import ReportReference

from .helpers import _write_selected_log


def test_cached_unranked_fight_backfills_report_date(monkeypatch, tmp_path: Path) -> None:
    directory = tmp_path / "report/fight-1/source-2"
    _write_selected_log(directory, 2)
    (directory / "fight.json").write_text('{"id":1,"startTime":500}')
    monkeypatch.setenv("FFLOGS_CLIENT_ID", "test")
    monkeypatch.setenv("FFLOGS_CLIENT_SECRET", "test")
    calls = []

    def backfill(reference: ReportReference, destination: Path) -> None:
        calls.append((reference, destination))
        (destination / "fight.json").write_text(
            '{"id":1,"startTime":500,"reportStartTime":1777593600000}'
        )

    monkeypatch.setattr(cli, "refresh_report_date", backfill)
    cli._verify_supported_fight(directory)
    assert calls == [(ReportReference("report", 1, 2), directory)]



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
        ("doomtrain", 1083),
        ("enuo", 1084),
    ],
)
@pytest.mark.parametrize(
    "alias, expected_job", [("MCH", "machinist"), ("brd", "bard"), ("BARD", "bard")]
)
def test_cli_rankings_shortcuts_compare_top_logs(
    monkeypatch, tmp_path: Path, capsys, fight: str, encounter: int,
    alias: str, expected_job: str,
) -> None:
    from ffxiv_potency.fflogs import ReportReference

    seen = []

    def fake_rankings(encounter_id: int, job: str, *, partition: int | None):
        assert (encounter_id, job) == (encounter, expected_job)
        assert partition is None
        return (
            ((1, ReportReference("abc123", 9, 18)),
             (3, ReportReference("def456", 4, 7))),
            ((2, "report unavailable"),),
        )

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        assert output == tmp_path and announce is False
        seen.append(source)
        return tmp_path / ("1" if "abc123" in source else "2")

    def fake_compare(directories, override, *, rank_positions=None, skip_analysis_errors=False):
        assert directories == [tmp_path / "1", tmp_path / "2"]
        assert override is None
        assert rank_positions == (1, 3)
        assert skip_analysis_errors
        print("Fight: Test Boss (101)")
        return ()

    monkeypatch.setattr(cli, "accessible_ranked_sources", fake_rankings)
    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    assert cli.main(["fflogs", alias, fight, "--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "Fight: Test Boss (101)" in output
    assert "Skipped ranks: 2 (report unavailable)" in output
    assert list(tmp_path.glob("ranks-*.json")) == []
    assert any("abc123?fight=9&source=18" in url for url in seen)
    assert any("def456?fight=4&source=7" in url for url in seen)



def test_top_ten_skips_one_unanalyzable_rank_and_shows_its_reason(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    from ffxiv_potency.analysis import AnalysisError

    def fake_rankings(encounter_id: int, job: str, *, partition: int | None):
        assert (encounter_id, job, partition) == (1085, "bard", None)
        return (
            ((1, ReportReference("bad123", 24, 490)),
             (2, ReportReference("good456", 7, 2))),
            (),
        )

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        return tmp_path / ("bad" if "bad123" in source else "good")

    def fake_analyze(directory: Path, actions: Path) -> AnalysisResult:
        if directory.name == "bad":
            raise AnalysisError("cannot match Stormbite tick to a landed DoT application")
        return AnalysisResult(
            fight_name="Dancing Mad", encounter_id=1085, source_name="Bard",
            ndps=1, duration_seconds=100, raw_damage_events=1,
            landed_damage_events=1, matched_damage_events=1,
            potency_min=100, potency_max=100, actions=(), auto_attacks=(),
            pet_deployments=(), hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
            potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
        )

    monkeypatch.setattr(cli, "accessible_ranked_sources", fake_rankings)
    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_source_job", lambda _: "bard")
    monkeypatch.setattr(cli, "_actions_for_job", lambda job, override: tmp_path / "actions.json")
    monkeypatch.setattr(cli, "_verify_supported_fight", lambda _: None)
    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)
    assert cli.main(["fflogs", "brd", "umad", "--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "   2  Bard" in output
    assert "Skipped ranks: 1 (cannot match Stormbite tick to a landed DoT application)" in output



def test_cli_rejects_nonpositive_rank(capsys) -> None:
    assert cli.main(["fflogs", "brd", "umad", "0"]) == 1
    assert "rank must be a positive number" in capsys.readouterr().err



def test_cli_selects_global_echo_partition(monkeypatch, capsys) -> None:
    def missing_rank(encounter_id: int, job: str, rank: int, *, partition: int) -> None:
        assert (encounter_id, job, rank, partition) == (101, "machinist", 1, 13)
        raise cli.FFLogsError("report unavailable")

    monkeypatch.setattr(cli, "ranked_source", missing_rank)
    assert cli.main(["fflogs", "mch", "m9s", "1", "--partition", "13"]) == 1
    assert "report unavailable" in capsys.readouterr().err



def test_cli_rejects_other_region_partition(capsys) -> None:
    assert cli.main(["fflogs", "brd", "m9s", "--partition", "9"]) == 1
    assert "partition 9 is not supported" in capsys.readouterr().err



def test_cli_passes_rank_beyond_ten_to_leaderboard(monkeypatch, capsys) -> None:
    def missing_rank(
        encounter_id: int, job: str, rank: int, *, partition: int | None,
    ) -> None:
        assert (encounter_id, job, rank) == (1085, "bard", 42)
        assert partition is None
        raise cli.FFLogsError("rank 42 does not exist for bard in encounter 1085")

    monkeypatch.setattr(cli, "ranked_source", missing_rank)
    assert cli.main(["fflogs", "brd", "umad", "42"]) == 1
    assert "rank 42 does not exist" in capsys.readouterr().err



def test_cli_compares_inclusive_rank_range(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_range(
        encounter_id: int, job: str, first: int, last: int, *, partition: int | None,
    ):
        assert (encounter_id, job, first, last) == (103, "machinist", 5000, 5024)
        assert partition is None
        return (
            ((5000, ReportReference("abc123", 9, 2)),
             (5024, ReportReference("def456", 3, 7))),
            ((5001, "report inaccessible"),),
        )

    def fake_compare(urls, output, actions, progress, *, rank_positions, skip_analysis_errors):
        assert output == tmp_path and actions is None
        assert rank_positions == (5000, 5024)
        assert skip_analysis_errors
        assert "abc123?fight=9&source=2" in urls[0]
        assert "def456?fight=3&source=7" in urls[1]
        print("Fight: The Tyrant (103)")
        return ((5024, "could not determine weapon delay"),)

    monkeypatch.setattr(cli, "ranked_sources_in_range", fake_range)
    monkeypatch.setattr(cli, "_download_and_compare", fake_compare)
    assert cli.main(["fflogs", "mch", "m11s", "5000-5024", "--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "Skipped ranks: 5001 (report inaccessible), 5024 (could not determine weapon delay)" in output
    assert list(tmp_path.glob("ranks-*.json")) == []



def test_cli_compares_selected_rank_positions(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_positions(encounter_id, job, positions, *, partition):
        assert (encounter_id, job, positions, partition) == (
            102, "machinist", (1, 2, 3, 153), None,
        )
        return (((1, ReportReference("abc123", 9, 2)),
                 (153, ReportReference("def456", 3, 7))), ((2, "unavailable"),))

    def fake_compare(urls, output, actions, progress, *, rank_positions, skip_analysis_errors):
        assert rank_positions == (1, 153)
        assert skip_analysis_errors
        return ()

    monkeypatch.setattr(cli, "ranked_sources_at_positions", fake_positions)
    monkeypatch.setattr(cli, "_download_and_compare", fake_compare)
    assert cli.main(["fflogs", "mch", "m10s", "1,2,3,153", "--output", str(tmp_path)]) == 0
    assert "Skipped ranks: 2 (unavailable)" in capsys.readouterr().out
    assert list(tmp_path.glob("ranks-*.json")) == []



def test_cli_rejects_duplicate_selected_ranks(capsys) -> None:
    assert cli.main(["fflogs", "mch", "m10s", "1,1"]) == 1
    assert "distinct positive" in capsys.readouterr().err



def test_cli_uses_dungeon_encounter_and_default_partition(monkeypatch, capsys) -> None:
    def missing_rank(encounter_id: int, job: str, rank: int, *, partition: int | None):
        assert (encounter_id, job, rank, partition) == (4551, "bard", 1, None)
        raise cli.FFLogsError("no dungeon ranking available")

    monkeypatch.setattr(cli, "ranked_source", missing_rank)
    assert cli.main(["fflogs", "brd", "clyteum", "1"]) == 1
    assert "no dungeon ranking available" in capsys.readouterr().err



def test_rank_range_keeps_comparing_after_unavailable_download(monkeypatch, tmp_path: Path) -> None:
    urls = ["first", "missing", "third"]

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        if source == "missing":
            raise cli.FFLogsError("report unavailable")
        return tmp_path / source

    def fake_compare(directories, actions, *, rank_positions, skip_analysis_errors):
        assert directories == [tmp_path / "first", tmp_path / "third"]
        assert rank_positions == (5000, 5002)
        assert skip_analysis_errors
        return ((5002, "analysis incomplete"),)

    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    with cli._Progress() as progress:
        skipped = cli._download_and_compare(
            urls, tmp_path, None, progress,
            rank_positions=(5000, 5001, 5002), skip_analysis_errors=True,
        )
    assert skipped == ((5001, "report unavailable"), (5002, "analysis incomplete"))



@pytest.mark.parametrize("value", ["0-10", "5-5", "10-5", "one-two", "5000-5025"])
def test_cli_rejects_invalid_rank_ranges(value: str, capsys) -> None:
    assert cli.main(["fflogs", "mch", "m11s", value]) == 1
    assert "rank" in capsys.readouterr().err



def test_rankings_show_current_step_before_lookup(monkeypatch, tmp_path: Path) -> None:

    from ffxiv_potency.fflogs import ReportReference

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal = Terminal()
    monkeypatch.setattr(cli.sys, "stderr", terminal)

    def fake_rankings(encounter_id: int, job: str, *, partition: int | None, on_status, on_progress):
        assert terminal.getvalue() == "\rConnecting to FF Logs..."
        assert partition is None
        on_progress(0, 10)
        on_status("Loading leaderboard page 1...")
        on_status("Identifying player for rank 1...")
        on_progress(1, 10)
        on_progress(10, 10)
        return (
            ((1, ReportReference("abc123", 9, 18)),
             (2, ReportReference("def456", 4, 7))),
            (),
        )

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        return tmp_path / "saved"

    def fake_compare(directories, override, progress, *, rank_positions=None,
                     skip_analysis_errors=False):
        assert rank_positions == (1, 2)
        assert skip_analysis_errors
        progress.clear()
        return ()

    monkeypatch.setattr(cli, "accessible_ranked_sources", fake_rankings)
    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    assert cli.main(["fflogs", "mch", "m10s", "--output", str(tmp_path)]) == 0
    assert "Loading leaderboard page 1..." in terminal.getvalue()
    assert "Identifying player for rank 1..." in terminal.getvalue()
    assert "Looking up ranks: [--------------------] 0/10" in terminal.getvalue()
    assert "Looking up ranks: [####################] 10/10" in terminal.getvalue()
    assert terminal.getvalue().index("Looking up ranks:") < terminal.getvalue().index("Loading fight data:")
    assert "Loading fight data:" in terminal.getvalue()
    assert terminal.getvalue().endswith("\r")

