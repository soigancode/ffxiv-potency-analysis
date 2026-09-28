"""Anonymous BRD m10s regression: DoT ticks pause while the target is untargetable."""

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.brd.dots import reconstruct_brd_dots
from ffxiv_potency.fflogs import ReportReference


def test_anonymous_brd_dot_refresh_after_untargetable_phase(
    tmp_path: Path, extract_fight
) -> None:
    extract_fight(
        "bard_red_hot_deep_blue_anonymous.zip",
        "a-DNaXrgHGZ8PbCkfL/fight-22/source-7/",
    )
    master = json.loads((tmp_path / "master-data.json").read_text(encoding="utf-8"))
    names = {item["gameID"]: item["name"] for item in master["abilities"]}
    damage = json.loads((tmp_path / "damage-events.json").read_text(encoding="utf-8"))
    ticks = reconstruct_brd_dots(damage, names, 7)

    assert len(ticks) == 395
    assert all(tick.matched for tick in ticks)
    refreshed = [tick for tick in ticks if tick.application_packet == 17963]
    assert len(refreshed) == 30
    assert {tick.application_name for tick in refreshed} == {"Iron Jaws"}
    assert {tick.snapshot_buffs for tick in refreshed} == {"1002217."}

    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    result = analyze_saved_fight(tmp_path, actions)
    assert (result.source_name, result.encounter_id) == ("Player (7)", 102)
    assert result.unmatched == ()
    assert result.potency_min == pytest.approx(116378.79720375093)


def test_anonymous_brd_appears_as_anonymous_in_comparison(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "a-DNaXrgHGZ8PbCkfL/fight-22/source-7"
    directory.mkdir(parents=True)
    prefix = "a-DNaXrgHGZ8PbCkfL/fight-22/source-7/"
    with ZipFile(Path(__file__).parents[1] / "fixtures/logs/bard_red_hot_deep_blue_anonymous.zip") as z:
        for member in z.namelist():
            if member.startswith(prefix) and member.endswith(".json"):
                (directory / member.removeprefix(prefix)).write_bytes(z.read(member))
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    cli._compare_directories([directory, directory], actions, rank_positions=(9, 10))
    output = capsys.readouterr().out
    assert "   9 Anonymous" in output
    assert "  10 Anonymous" in output
    assert "Player (7)" not in output


def test_anonymous_brd_analysis_groups_landed_events(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight(
        "bard_red_hot_deep_blue_anonymous.zip",
        "a-DNaXrgHGZ8PbCkfL/fight-22/source-7/",
    )
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    cli._print_analysis(analyze_saved_fight(tmp_path, actions))
    output = capsys.readouterr().out
    assert "Player: Anonymous\n" in output
    assert (
        "Landed damage events: 910\n"
        "  Matched action events: 761\n"
        "  Matched auto-attacks: 149\n"
    ) in output
    assert "Matched potency events" not in output


def test_one_leaderboard_rank_shows_full_anonymous_analysis(
    tmp_path: Path, extract_fight, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight(
        "bard_red_hot_deep_blue_anonymous.zip",
        "a-DNaXrgHGZ8PbCkfL/fight-22/source-7/",
    )
    reference = ReportReference("a:DNaXrgHGZ8PbCkfL", 22, 7)
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    monkeypatch.setattr(cli, "ranked_source", lambda encounter, job, rank: (
        reference if (encounter, job, rank) == (102, "bard", 9) else None
    ))
    def resolve(source: str, output: Path, **kwargs) -> Path:
        assert "a:DNaXrgHGZ8PbCkfL?fight=22&source=7" in source
        assert kwargs["include_targetability"] is True
        return tmp_path

    monkeypatch.setattr(cli, "_resolve_analysis_directory", resolve)
    monkeypatch.setattr(cli, "_actions_for_job", lambda job, override: actions)
    assert cli.main(["fflogs", "brd", "m10s", "9"]) == 0
    output = capsys.readouterr().out
    assert "Player: Anonymous\nRank: 9\nFight: Red Hot" in output
    assert "Matched auto-attacks: 149" in output
