"""Independent MCH observations of revival, food, potion, and Damage Down."""

import json
from pathlib import Path
from statistics import median

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _print_analysis

ARCHIVE = "mch_tyrant_penalty_cases.zip"
ACTIONS = Path(__file__).parents[2] / "data/machinist/7.55/actions.json"


def _normal_damage(directory: Path, action: str, buffs: str) -> list[int]:
    master = json.loads((directory / "master-data.json").read_text())
    names = {row["gameID"]: row["name"] for row in master["abilities"]}
    events = json.loads((directory / "damage-events.json").read_text())
    return [
        event["amount"] for event in events
        if event.get("type") == "damage" and not event.get("tick")
        and names.get(event.get("abilityGameID")) == action
        and event.get("buffs", "") == buffs
        and event.get("hitType") == 1 and not event.get("directHit")
        and not event.get("overkill") and event.get("amount", 0) > 0
    ]


@pytest.mark.parametrize(
    "prefix, status, fraction, actions",
    [
        ("akyMcZh6HNKb7jJL/fight-35/source-737/", "1000043", 75,
         ("Blazing Shot", "Drill", "Heated Clean Shot", "Heated Split Shot")),
        ("WkZPjR4wnxKvaCcA/fight-5/source-9/", "1000044", 50,
         ("Blazing Shot", "Checkmate", "Double Check", "Heated Split Shot")),
    ],
)
def test_potted_revival_penalty_matches_independent_action_damage(
    tmp_path: Path, extract_fight, prefix: str, status: str, fraction: int,
    actions: tuple[str, ...],
) -> None:
    extract_fight(ARCHIVE, prefix)
    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert result.encounter_id == 103
    assert any(window.name == ("Weakness" if fraction == 75 else "Brink of Death")
               for window in result.status_windows)

    ratios = []
    for action in actions:
        ordinary = _normal_damage(tmp_path, action, "")
        potted_penalty = _normal_damage(tmp_path, action, f"{status}.1000049.")
        assert ordinary and potted_penalty, action
        ratios.append(median(potted_penalty) / median(ordinary))

    # Compare unmodified damage observations to the level-100 main-stat formula.
    # Individual hits have a ±5% roll, so use several independent action types.
    factor = lambda dex: 100 + 237 * (dex - 440) // 440
    expected = factor(7379 * fraction // 100) / factor(6838)
    assert median(ratios) == pytest.approx(expected, rel=0.04)


def test_food_expires_before_weakness_and_stays_absent_through_potion(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight(ARCHIVE, "akyMcZh6HNKb7jJL/fight-35/source-737/")
    actual = analyze_saved_fight(tmp_path, ACTIONS)
    assert len(actual.food_missing_windows) == 1
    assert actual.food_missing_windows[0] == pytest.approx((228.384, 651.055))
    assert actual.status_windows[1].name == "Weakness"
    assert actual.status_windows[1].start_seconds == pytest.approx(237.167)
    assert actual.potion.windows[0].start_seconds == pytest.approx(297.891)

    path = tmp_path / "buff-events.json"
    events = json.loads(path.read_text())
    path.write_text(json.dumps([
        event for event in events
        if not (event.get("targetID") == 737 and event.get("abilityGameID") == 1000048)
    ]))
    assumed_fed = analyze_saved_fight(tmp_path, ACTIONS)
    assert assumed_fed.food_missing_windows == ()
    assert actual.critical_gear_baseline < assumed_fed.critical_gear_baseline
    assert actual.luck_baseline < assumed_fed.luck_baseline
    assert actual.potency_min == pytest.approx(assumed_fed.potency_min)


def test_tyrant_damage_down_refresh_and_transcendent_revival(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str],
) -> None:
    extract_fight(ARCHIVE, "FgyM3HDBWV4z1ZRK/fight-42/source-1004/")
    # Observed in FF Logs Events at 06:48.356; the saved Buffs table omits
    # this Environment-sourced buff. New downloads obtain it via raw events.
    (tmp_path / "revival-buff-events.json").write_text(json.dumps([{
        "timestamp": 48762509, "type": "applybuff", "sourceID": -1, "targetID": 1004,
        "abilityGameID": 1000418,
    }]))
    result = analyze_saved_fight(tmp_path, ACTIONS)
    penalty = next(item for item in result.damage_penalties if item.name == "Damage Down")
    assert penalty.multiplier == 0.65
    assert penalty.affected_hits == 38
    windows = [item for item in result.status_windows if item.name == "Damage Down"]
    assert len(windows) == 1
    assert (windows[0].start_seconds, windows[0].end_seconds) == pytest.approx(
        (549.183, 587.176)
    )
    assert windows[0].refresh_seconds == pytest.approx((557.207,))
    assert windows[0].end_reason == "expired"
    assert any(item.name == "Dead" and item.start_seconds == pytest.approx(408.31)
               and item.end_seconds == pytest.approx(408.356)
               and item.end_reason == "revived: Healer LB3"
               for item in result.status_windows)

    ordinary = _normal_damage(tmp_path, "Blazing Shot", "")
    penalized = _normal_damage(tmp_path, "Blazing Shot", "1002911.")
    assert len(ordinary) >= 10 and len(penalized) >= 2
    assert median(penalized) / median(ordinary) == pytest.approx(0.65, rel=0.05)

    _print_analysis(result)
    output = capsys.readouterr().out
    assert "Damage Down: 09m09s–09m47s (refreshed at 09m17s; expired)" in output
    assert output.count("35% reduction; 38 landed hits affected") == 1


def test_tyrant_wildfire_snapshot_does_not_create_second_potion(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str],
) -> None:
    extract_fight(
        "mch_tyrant_potion_snapshot.zip", "xWtBLyD1wMnYN67p/fight-22/source-524/",
    )
    result = analyze_saved_fight(tmp_path, ACTIONS)

    assert result.potion.uses == 1
    assert len(result.potion.windows) == 1
    assert result.potion.windows[0].start_seconds == pytest.approx(599.633)
    assert result.potion.windows[0].end_seconds == pytest.approx(630.235)
    # Wildfire retains Medicated from its 10m28s application when it detonates
    # at 10m38s, even though the buff expired at 10m30s.
    assert result.mch_wildfires[-1].applied_seconds == pytest.approx(628.408)
    assert result.mch_wildfires[-1].detonated_seconds == pytest.approx(638.385)
    damage_down = next(p for p in result.damage_penalties if p.name == "Damage Down")
    assert damage_down.affected_hits == 68
    assert damage_down.lost_potency_min == pytest.approx(6794.054615384606)
    assert damage_down.lost_potency_max == pytest.approx(damage_down.lost_potency_min)

    _print_analysis(result)
    output = capsys.readouterr().out
    assert "  Uses: 1\n" in output
    assert "  Window 1: 10m00s–10m30s\n" in output
    assert "Window 2:" not in output
    assert (
        "Damage Down: 01m52s–02m22s (expired)\n"
        "  Damage Down: 03m26s–03m56s (expired)\n"
        "  Damage Down total (2 windows): 35% reduction; 68 landed hits affected; "
        "6,794 potency lost\n\nGhosted damaging casts:"
    ) in output

    damage_path = tmp_path / "damage-events.json"
    events = json.loads(damage_path.read_text())
    for event in events:
        if isinstance(event.get("buffs"), str):
            event["buffs"] = event["buffs"].replace("1002911.", "")
    damage_path.write_text(json.dumps(events))
    without_damage_down = analyze_saved_fight(tmp_path, ACTIONS)
    assert without_damage_down.potency_min - result.potency_min == pytest.approx(
        damage_down.lost_potency_min
    )
