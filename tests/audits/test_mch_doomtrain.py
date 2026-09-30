"""Doomtrain MCH log: a self-targeted channel cast without damage ticks."""

import json
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _format_fight, _print_analysis

ARCHIVE = "mch_doomtrain_sample.zip"
PREFIX = "czvapF4mr1XPJ8Kw/fight-1/source-4/"
ACTIONS = Path(__file__).parents[2] / "data/machinist/7.55/actions.json"


def test_doomtrain_self_targeted_flamethrower_cast_has_no_landed_ticks(
    tmp_path: Path, extract_fight, capsys,
) -> None:
    extract_fight(ARCHIVE, PREFIX)
    with ZipFile(Path(__file__).parents[1] / "fixtures/logs" / ARCHIVE) as archive:
        (tmp_path / "combatant-info-events.json").write_bytes(
            archive.read(PREFIX + "combatant-info-events.json")
        )
    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert result.unmatched == ()
    assert result.ghosted == (
        ("Blazing Shot", 1), ("Flamethrower", 1), ("Heated Split Shot", 1),
    )
    assert dict(result.ghosted_times)["Flamethrower"] == (57.496,)
    assert "Flamethrower" not in dict(result.ghosted_targets)
    assert _format_fight(result) == "Doomtrain (1083)"
    assert result.food is not None
    assert result.food_missing_windows == ()
    _print_analysis(result)
    output = capsys.readouterr().out
    assert "Flamethrower" in output
    assert "Flamethrower on " not in output
    assert _format_fight(replace(result, fight_name="グラシャラボラス")) == "Doomtrain (1083)"


def test_no_initial_food_or_application_means_unfed_fight(
    tmp_path: Path, extract_fight, capsys,
) -> None:
    extract_fight(ARCHIVE, PREFIX)
    with ZipFile(Path(__file__).parents[1] / "fixtures/logs" / ARCHIVE) as archive:
        combatants = json.loads(archive.read(PREFIX + "combatant-info-events.json"))
    (tmp_path / "combatant-info-events.json").write_text(json.dumps(combatants))
    fed = analyze_saved_fight(tmp_path, ACTIONS)
    initial = next(event for event in combatants if event["sourceID"] == 4)
    initial["auras"] = [aura for aura in initial["auras"] if aura["ability"] != 1000048]
    (tmp_path / "combatant-info-events.json").write_text(json.dumps(combatants))

    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert result.food is None
    assert result.food_missing_windows == ((0, result.duration_seconds),)
    assert result.critical_gear_baseline < fed.critical_gear_baseline
    assert result.potency_min == fed.potency_min
    _print_analysis(result)
    assert "Food: None\n" in capsys.readouterr().out
