"""Doomtrain BRD log without the Well Fed aura or any food application."""

from pathlib import Path
from zipfile import ZipFile

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _print_analysis


def test_brd_doomtrain_without_food(tmp_path: Path, extract_fight, capsys) -> None:
    archive_name = "brd_doomtrain_without_food.zip"
    prefix = "XhcqCfrJzNgZdQxP/fight-1/source-8/"
    extract_fight(archive_name, prefix)
    with ZipFile(Path(__file__).parents[1] / "fixtures/logs" / archive_name) as archive:
        (tmp_path / "combatant-info-events.json").write_bytes(
            archive.read(prefix + "combatant-info-events.json")
        )
    result = analyze_saved_fight(tmp_path, Path("data/bard/7.55/actions.json"))
    assert result.encounter_id == 1083
    assert result.food is None
    assert result.food_missing_windows == ((0, result.duration_seconds),)
    assert result.unmatched == ()
    assert not any(penalty.name == "Damage Down" for penalty in result.damage_penalties)
    _print_analysis(result)
    assert "Food: None\n" in capsys.readouterr().out
