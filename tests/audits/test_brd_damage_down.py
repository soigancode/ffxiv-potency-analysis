"""An ultimate wipe with Damage Down and an old DoT snapshot."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.brd.dots import brd_dot_potency, reconstruct_brd_dots
from ffxiv_potency.analysis.penalties import load_damage_penalties
from ffxiv_potency.cli import _print_analysis


def test_damage_down_scales_only_affected_hits(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight("brd_damage_down.zip", "nRdCmKkJP1XjYf29/fight-1/source-2/")
    actions = Path(__file__).parents[2] / "data/bard/7.55/actions.json"
    result = analyze_saved_fight(tmp_path, actions)

    assert result.encounter_id == 1085
    assert result.damage_penalties[0].name == "Damage Down"
    assert result.damage_penalties[0].multiplier == 0.1
    assert result.damage_penalties[0].affected_hits == 80
    assert result.damage_penalties[0].first_observed_seconds == pytest.approx(40.397)
    assert result.damage_penalties[0].last_observed_seconds == pytest.approx(89.857)
    window = next(item for item in result.status_windows if item.name == "Damage Down")
    assert window.start_seconds == pytest.approx(39.016)
    assert window.refresh_seconds == (pytest.approx(89.012),)
    assert window.end_seconds == pytest.approx(89.147)
    assert window.end_reason == "removed"
    assert result.auto_attacks[0].weapon_delay_seconds == 3.04
    assert result.potency_min == pytest.approx(10923.91886653846)
    for dot in result.brd_dots:
        action = next(action for action in result.actions if action.name == dot.name)
        assert dot.total_potency == pytest.approx(action.potency_min)

    master = json.loads((tmp_path / "master-data.json").read_text())
    names = {row["gameID"]: row["name"] for row in master["abilities"]}
    damage = json.loads((tmp_path / "damage-events.json").read_text())
    ticks = reconstruct_brd_dots(damage, names, 2)
    start = json.loads((tmp_path / "fight.json").read_text())["startTime"]
    old_snapshot = next(t for t in ticks if t.name == "Stormbite" and t.timestamp == start + 41864)
    refreshed = next(t for t in ticks if t.name == "Stormbite" and t.timestamp == start + 47830)
    rules = load_damage_penalties(1085)
    assert brd_dot_potency(
        old_snapshot, 25, potion_multiplier=1, self_buff_windows={}, damage_penalties=rules,
    ) == pytest.approx(25)
    assert brd_dot_potency(
        refreshed, 25, potion_multiplier=1, self_buff_windows={}, damage_penalties=rules,
    ) == pytest.approx(2.5)

    with patch("ffxiv_potency.analysis.analyze.load_damage_penalties", return_value={}):
        unpenalized = analyze_saved_fight(tmp_path, actions)
    assert unpenalized.potency_min == pytest.approx(20272.071231923077)
    assert result.potency_min < unpenalized.potency_min

    _print_analysis(result)
    output = capsys.readouterr().out
    assert output.index("Damage penalties:") < output.index("Variable potency:")
    assert "Damage Down: 00m39s–01m29s (refreshed at 01m29s; removed)" in output
    assert "90% reduction; 80 landed hits affected" in output


def test_damage_down_refresh_and_ticks_after_death_use_snapshot(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight("brd_damage_down_refresh.zip", "CLgcPdnVR47aZ1kQ/fight-28/source-13/")
    actions = Path(__file__).parents[2] / "data/bard/7.55/actions.json"
    result = analyze_saved_fight(tmp_path, actions)

    assert result.unmatched == ()
    damage_down = next(window for window in result.status_windows if window.name == "Damage Down")
    assert damage_down.start_seconds == pytest.approx(688.798)
    assert damage_down.refresh_seconds == (pytest.approx(717.079),)
    assert damage_down.end_seconds == pytest.approx(719.09)
    assert damage_down.end_reason == "death"

    affected = next(item for item in result.damage_penalties if item.name == "Damage Down")
    assert affected.multiplier == 0.1
    assert affected.affected_hits == 43
    assert affected.last_observed_seconds == pytest.approx(733.376)

    fight = json.loads((tmp_path / "fight.json").read_text())
    master = json.loads((tmp_path / "master-data.json").read_text())
    names = {ability["gameID"]: ability["name"] for ability in master["abilities"]}
    damage = json.loads((tmp_path / "damage-events.json").read_text())
    ticks = reconstruct_brd_dots(damage, names, 13)
    after_death = next(
        tick for tick in ticks
        if tick.name == "Stormbite" and tick.timestamp - fight["startTime"] == 733_376
    )
    assert after_death.matched
    assert after_death.snapshot_timestamp - fight["startTime"] == 708_258
    assert "1002911" in after_death.snapshot_buffs.split(".")  # Damage Down at application.
    assert brd_dot_potency(
        after_death, 25, potion_multiplier=1, self_buff_windows={},
        damage_penalties=load_damage_penalties(1085),
    ) == pytest.approx(2.5)
