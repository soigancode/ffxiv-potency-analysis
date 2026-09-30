"""CLI selection of a fight and player from a report URL."""

from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.fflogs import DownloadResult, ReportReference
from ffxiv_potency.fflogs.selection import ReportFight, ReportPlayer


def _fights() -> tuple[ReportFight, ...]:
    return (
        ReportFight(9, "Boss", 101, 120.0, False,
                    (ReportPlayer(18, "Alice", "Bard"),
                     ReportPlayer(19, "Other", "Dancer"))),
        ReportFight(10, "Boss", 101, 90.0, True,
                    (ReportPlayer(20, "Bob", "Machinist"),)),
        ReportFight(11, "Unsupported", 9999, 60.0, True,
                    (ReportPlayer(21, "Charlie", "Bard"),)),
    )


def test_unselected_report_prompts_for_multiple_fights(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "report_fights", lambda code: _fights())
    answers = iter(("bad", "2"))
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert cli._select_report_reference(
        "https://www.fflogs.com/reports/XhcqCfrJzNgZdQxP"
    ) == ReportReference("XhcqCfrJzNgZdQxP", 10, 20)
    output = capsys.readouterr().out
    assert "1. Boss (fight 9, 02m00s) (wipe)" in output
    assert "2. Boss (fight 10, 01m30s)" in output
    assert "Unsupported" not in output
    assert "Enter a number from 1 to 2." in output
    assert "Player: Bob (Machinist, source 20)" in output
    assert "Players:" not in output
    assert "Other" not in output


def test_single_fight_and_player_are_selected_without_input(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "report_fights", lambda code: (_fights()[1],))

    def no_prompt(prompt: str) -> str:
        raise AssertionError("single choices must not prompt")

    monkeypatch.setattr("builtins.input", no_prompt)
    assert cli._select_report_reference(
        "https://www.fflogs.com/reports/abc123"
    ) == ReportReference("abc123", 10, 20)
    output = capsys.readouterr().out
    assert "Fight: Boss (fight 10, 01m30s)" in output
    assert "Player: Bob (Machinist, source 20)" in output
    assert "Choose" not in output


def test_single_fight_with_multiple_players_prompts_only_for_player(monkeypatch, capsys) -> None:
    fight = ReportFight(9, "Boss", 101, None, True,
                        (ReportPlayer(18, "Alice", "Bard"),
                         ReportPlayer(20, "Bob", "Machinist")))
    monkeypatch.setattr(cli, "report_fights", lambda code: (fight,))
    prompts = []

    def choose(prompt: str) -> str:
        prompts.append(prompt)
        return "2"

    monkeypatch.setattr("builtins.input", choose)
    assert cli._select_report_reference(
        "https://www.fflogs.com/reports/abc123"
    ) == ReportReference("abc123", 9, 20)
    assert prompts == ["Choose player [1-2]: "]
    output = capsys.readouterr().out
    assert "Fight: Boss (fight 9)" in output
    assert "1. Alice (Bard, source 18)" in output
    assert "2. Bob (Machinist, source 20)" in output


def test_partial_and_complete_urls_do_not_repeat_selection(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "report_fights", lambda code: _fights())
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(
        AssertionError("single player must be selected automatically")
    ))
    assert cli._select_report_reference(
        "https://www.fflogs.com/reports/abc123?fight=10"
    ) == ReportReference("abc123", 10, 20)
    assert "Fights:" not in capsys.readouterr().out

    monkeypatch.setattr(cli, "report_fights", lambda code: (_ for _ in ()).throw(
        AssertionError("selected URLs must not fetch choices")
    ))
    assert cli._select_report_reference(
        "https://www.fflogs.com/reports/abc123?fight=10&source=20"
    ) == ReportReference("abc123", 10, 20)


def test_selection_requires_input_and_rejects_unsupported_player(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "report_fights", lambda code: _fights())

    def no_input(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    assert cli.main(["analyse", "https://www.fflogs.com/reports/abc123"]) == 1
    assert "needs interactive input" in capsys.readouterr().err
    assert cli.main(["fflogs", "https://www.fflogs.com/reports/abc123?source=19"]) == 1
    assert "not a supported player" in capsys.readouterr().err


@pytest.mark.parametrize("source", ["abc123", "https://www.fflogs.com/reports/abc123"])
def test_analyse_unselected_url_passes_selected_source_to_downloader(
    source, monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "report_fights", lambda code: _fights())
    answers = iter(("2",))
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    def fake_resolve(source: str, output: Path, **kwargs) -> Path:
        assert source == "https://www.fflogs.com/reports/abc123?fight=10&source=20"
        assert output == tmp_path
        raise ValueError("selection reached downloader")

    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    assert cli.main(["analyse", source,
                     "--output", str(tmp_path)]) == 1
    assert "selection reached downloader" in capsys.readouterr().err


@pytest.mark.parametrize("source", ["abc123", "https://www.fflogs.com/reports/abc123"])
def test_fflogs_unselected_url_downloads_chosen_fight(source, monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "report_fights", lambda code: _fights())
    answers = iter(("1",))
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    directory = tmp_path / "abc123/fight-9/source-18"

    def fake_download(reference: ReportReference, output: Path) -> DownloadResult:
        assert reference == ReportReference("abc123", 9, 18)
        assert output == tmp_path
        return DownloadResult(
            directory, directory / "fight.json", directory / "master-data.json",
            directory / "damage-events.json", directory / "cast-events.json",
            directory / "rankings.json", 12, 3,
        )

    monkeypatch.setattr(cli, "download_report_events", fake_download)
    assert cli.main(["fflogs", source,
                     "--output", str(tmp_path)]) == 0
    assert "Damage events: 12" in capsys.readouterr().out


def test_compare_selects_players_from_bare_report_ids(monkeypatch) -> None:
    monkeypatch.setattr(cli, "report_fights", lambda code: (_fights()[1],))
    received = []

    def fake_compare(sources, *args, **kwargs):
        received.extend(sources)
        return 0

    monkeypatch.setattr(cli, "_download_and_compare", fake_compare)
    assert cli.main(["compare", "abc123", "def456"]) == 0
    assert received == [
        "https://www.fflogs.com/reports/abc123?fight=10&source=20",
        "https://www.fflogs.com/reports/def456?fight=10&source=20",
    ]
