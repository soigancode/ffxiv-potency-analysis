"""Tests for compare behavior."""

import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import (
    AnalysisResult,
    HitOutcomeSummary,
    PotionSummary,
)
from ffxiv_potency.fflogs import DownloadResult

from .helpers import _write_selected_log


@pytest.mark.parametrize(("job", "ndps", "combined"), [
    ("warrior", 1000, True), ("machinist", 1000, True),
    ("bard", 1000, False), ("dancer", 1000, False),
    ("warrior", 999, False), ("machinist", None, False),
])
def test_comparison_combines_equal_damage_metrics(monkeypatch, tmp_path, capsys, job, ndps, combined):
    result = AnalysisResult(
        fight_name="Boss", encounter_id=1085, source_name="Player", ndps=ndps, rdps=1000,
        duration_seconds=10, raw_damage_events=0, landed_damage_events=0,
        matched_damage_events=0, potency_min=0, potency_max=0, actions=(),
        auto_attacks=(), pet_deployments=(), hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
    )
    monkeypatch.setattr(cli, "_source_job", lambda directory: job)
    monkeypatch.setattr(cli, "_actions_for_job", lambda *args: tmp_path / "actions.json")
    monkeypatch.setattr(cli, "_verify_supported_fight", lambda directory: None)
    monkeypatch.setattr(cli, "analyze_saved_fight", lambda *args: result)
    cli._compare_directories([tmp_path, tmp_path], None)
    header = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("Player "))
    assert ("rDPS/nDPS" in header) is combined
    if not combined:
        assert "rDPS" in header and "nDPS" in header


def test_cli_compares_supplied_warrior_logs(war_saved_sources, capsys):
    urls = []
    for directory in war_saved_sources[:2]:
        reference = cli._reference_from_directory(directory)
        assert reference is not None
        urls.append(f"https://www.fflogs.com/reports/{reference.report_code}"
                    f"?fight={reference.fight_id}&source={reference.source_id}")
    assert cli.main(["compare", *urls]) == 0
    output = capsys.readouterr().out
    assert "Poto Gota" in output and "Chad Bradly" in output


def test_cli_rejects_previous_partition_for_analyse_and_compare(
    tmp_path: Path, capsys,
) -> None:
    old = tmp_path / "oldreport/fight-9/source-2"
    current = tmp_path / "newreport/fight-9/source-3"
    _write_selected_log(old, 2)
    _write_selected_log(current, 3)
    for directory in (old, current):
        fight = json.loads((directory / "fight.json").read_text())
        fight["encounterID"] = 103
        (directory / "fight.json").write_text(json.dumps(fight))
    (old / "rankings.json").write_text(json.dumps({
        "metric": "ndps", "rdps": {},
        "rankings": {"data": [{"fightID": 9, "partition": 6, "bracketData": 7.4}]},
    }))
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")

    assert cli.main(["analyse", str(old), "--actions", str(actions)]) == 1
    assert "partition 6" in capsys.readouterr().err
    urls = [
        f"https://www.fflogs.com/reports/{code}?fight=9&source={source}"
        for code, source in (("oldreport", 2), ("newreport", 3))
    ]
    assert cli.main(["compare", *urls, "--actions", str(actions),
                     "--output", str(tmp_path)]) == 1
    assert "partition 6" in capsys.readouterr().err



def test_compare_anonymous_player_uses_terminal_italics(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "a-DNaXrgHGZ8PbCkfL/fight-22/source-7"
    assert cli._comparison_player_field("Player (7)", path) == f"{'Anonymous':<24}"

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(cli.sys, "stdout", Terminal())
    field = cli._comparison_player_field("Player (7)", path)
    assert field == "\x1b[3mAnonymous\x1b[23m" + " " * (24 - len("Anonymous"))
    assert cli._comparison_player_field("Alice", tmp_path / "abc/fight-1/source-3") == (
        f"{'Alice':<24}"
    )



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
    assert "Fight: Boss" in output
    assert "01m40s" in output
    assert "nDPS" in output and "15,000.0" in output
    assert "rDPS" in output and "15,100.0" in output
    assert "Player" in output and "aLuck" in output and "45.12%" in output
    assert next(line for line in output.splitlines() if line.startswith("Player")).endswith("Date")
    assert all(line.endswith("01/05/26") for line in output.splitlines()
               if line.startswith(("Alice", "Bob")))
    assert "Rank" not in output
    assert "aLuck" in output and "45.12%" in output
    header = next(line for line in output.splitlines() if line.startswith("Player"))
    assert header.index("PPS") < header.index("aHB") < header.index("aLuck")
    assert "HB" not in header.split()
    assert "nDPS  Potency" in output
    assert header.split()[-4:] == ["Notes", "Partition", "Patch", "Date"]
    assert "Party" not in output and "Echo" not in output
    assert "Crit" not in output and "DH" not in output and "CDH" not in output
    assert "Alice" in output and "1,000" in output and "10" in output
    assert "Bob" in output and "1,200" in output and "12" in output

    cli._compare_directories(
        [tmp_path / "abc123/fight-9/source-18", tmp_path / "def456/fight-2/source-7"],
        actions,
        rank_positions=(1, 9),
    )
    ranked_output = capsys.readouterr().out
    assert "Rank  Player" in ranked_output
    assert "Fight: Boss\nPartition: n/a\nPatch: 7.5\n" in ranked_output
    header = next(line for line in ranked_output.splitlines() if line.startswith("Rank"))
    assert "Partition" not in header and "Patch" not in header
    assert any(line.startswith("   1  Alice") for line in ranked_output.splitlines())
    assert any(line.startswith("   9  Bob") for line in ranked_output.splitlines())
    assert all(line.endswith("01/05/26") for line in ranked_output.splitlines()
               if line.startswith(("   1  Alice", "   9  Bob")))

    def dated_result(directory: Path, actions_path: Path) -> AnalysisResult:
        return replace(fake_analyze(directory, actions_path),
                       played_patch="7.51" if "abc123" in str(directory) else "7.55",
                       gear_name="7.55 Relic BiS", gear_source="assumed")

    monkeypatch.setattr(cli, "analyze_saved_fight", dated_result)
    cli._compare_directories(
        [tmp_path / "abc123/fight-9/source-18", tmp_path / "def456/fight-2/source-7"],
        actions, rank_positions=(1, 9),
    )
    dated_output = capsys.readouterr().out
    assert "Fight: Boss\nPartition: n/a\nPatch: 7.5\n" in dated_output
    dated_header = next(line for line in dated_output.splitlines() if line.startswith("Rank"))
    assert "Partition" not in dated_header and "Patch" not in dated_header
    assert "Gear" not in dated_output and "BiS" not in dated_output
    assert "7.51" not in dated_output and "7.55" not in dated_output
    cli._compare_directories([tmp_path / "abc123/fight-9/source-18"], actions)
    comparison_output = capsys.readouterr().out
    assert "7.51" not in comparison_output and "BiS" not in comparison_output

    def wide_potency(directory: Path, actions_path: Path) -> AnalysisResult:
        return replace(fake_analyze(directory, actions_path),
                       potency_min=248364, potency_max=248364)

    monkeypatch.setattr(cli, "analyze_saved_fight", wide_potency)
    cli._compare_directories([tmp_path / "abc123/fight-9/source-18"], actions)
    compact_output = capsys.readouterr().out
    assert "15,000.0  248,364" in compact_output
    assert "45.12% - n/a 7.5 01/05/26" in " ".join(compact_output.split())

    for encounter in (4549, 4550, 4551):
        def dungeon_result(
            directory: Path, actions_path: Path, encounter_id: int = encounter,
        ) -> AnalysisResult:
            return replace(fake_analyze(directory, actions_path),
                           encounter_id=encounter_id, dps=16789.2)

        monkeypatch.setattr(cli, "analyze_saved_fight", dungeon_result)
        for ranks in (None, (1,)):
            cli._compare_directories([tmp_path / "abc123/fight-9/source-18"],
                                     actions, rank_positions=ranks)
            dungeon_output = capsys.readouterr().out
            if encounter in (4549, 4551):
                assert "DPS" in dungeon_output and "16,789.2" in dungeon_output
                assert "rDPS" not in dungeon_output and "nDPS" not in dungeon_output
            assert "dPPS" in dungeon_output
            if ranks is not None:
                assert "dPPS:" not in dungeon_output
                assert "Partition" not in dungeon_output
                assert "Patch: 7.5" in dungeon_output
    monkeypatch.setattr(cli, "analyze_saved_fight", fake_analyze)

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
    monkeypatch.setattr(cli, "load_manifest", lambda job: (
        {"action_sets": [{"id": "actions_7_4", "file": "7.4/actions.json",
                          "valid_from": "7.4", "verified_through": "7.55"}]},
        tmp_path / "data/jobs/mch",
    ))
    _write_selected_log(tmp_path / "data/logs/abc/fight-1/source-2", 2)
    _write_selected_log(tmp_path / "data/logs/def/fight-1/source-3", 3)
    urls = [
        "https://www.fflogs.com/reports/abc?fight=1&source=2",
        "https://www.fflogs.com/reports/def?fight=1&source=3",
    ]

    assert cli.main(["compare", *urls]) == 1
    error = capsys.readouterr().err
    assert "data/jobs/mch/7.4/actions.json" in error
    assert "jobguide machinist" in error



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
