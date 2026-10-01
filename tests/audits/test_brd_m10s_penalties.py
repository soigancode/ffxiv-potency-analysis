"""Current savage BRD logs with food expiry and repeated revivals."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.brd.dots import brd_dot_potency, reconstruct_brd_dots
from ffxiv_potency.analysis.profiles import _load_combat_profile

ARCHIVE = "brd_m10s_penalty_cases.zip"
ACTIONS = Path(__file__).parents[2] / "data/jobs/brd/7.4/actions.json"


def test_food_expires_during_dots_and_lb3_precedes_weakness(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight(ARCHIVE, "YGgjAdmcbk3ynrXw/fight-52/source-3/")
    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert result.unmatched == ()
    damage_down = next(penalty for penalty in result.damage_penalties
                       if penalty.name == "Damage Down")
    assert damage_down.multiplier == 0.70
    assert damage_down.affected_hits == 50
    assert damage_down.first_observed_seconds == pytest.approx(281.26)
    # Ticks retain the application snapshot after the status expires at 307.911s.
    assert damage_down.last_observed_seconds == pytest.approx(337.628)
    assert result.food_missing_windows == (pytest.approx((309.606, 593.753)),)
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason)
            for w in result.status_windows] == [
        ("Damage Down", pytest.approx(277.919), pytest.approx(307.911), "expired"),
        ("Dead", pytest.approx(454.355), pytest.approx(462.876), "revived: Healer LB3"),
        ("Dead", pytest.approx(550.115), pytest.approx(587.279),
         "revived: Weakness applied"),
        ("Weakness", pytest.approx(587.279), pytest.approx(593.753), "fight ended"),
    ]

    fight = json.loads((tmp_path / "fight.json").read_text())
    master = json.loads((tmp_path / "master-data.json").read_text())
    names = {ability["gameID"]: ability["name"] for ability in master["abilities"]}
    damage = json.loads((tmp_path / "damage-events.json").read_text())
    # The same song status has a 1.00 FF Logs multiplier without Damage Down,
    # and 0.70 with it. This establishes the encounter-specific strength.
    assert {event.get("multiplier") for event in damage
            if event.get("type") == "damage" and event.get("amount", 0) > 0
            and event.get("buffs") == "1002216."} == {1}
    assert {event.get("multiplier") for event in damage
            if event.get("type") == "damage" and event.get("amount", 0) > 0
            and event.get("buffs") == "1002911.1002216."} == {0.7}
    ticks = reconstruct_brd_dots(damage, names, 3)
    assert any(
        tick.name == "Stormbite"
        and tick.snapshot_timestamp is not None
        and tick.snapshot_timestamp < fight["startTime"] + 309606 < tick.timestamp
        for tick in ticks
    )

    # This second analysis changes only the food observation, checking that
    # its absence changes the expected Crit rate for a real BRD fight.
    buff_path = tmp_path / "buff-events.json"
    buffs = json.loads(buff_path.read_text())
    buff_path.write_text(json.dumps([
        event for event in buffs
        if not (event.get("targetID") == 3 and event.get("abilityGameID") == 1000048)
    ]))
    assumed_fed = analyze_saved_fight(tmp_path, ACTIONS)
    assert assumed_fed.food_missing_windows == ()
    assert result.critical_gear_baseline < assumed_fed.critical_gear_baseline


def test_brink_refresh_after_another_death_starts_fresh_window(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight(ARCHIVE, "NVJkZ16xCbpLmrHw/fight-21/source-345/")
    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert result.unmatched == ()
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason)
            for w in result.status_windows] == [
        ("Dead", pytest.approx(299.667), pytest.approx(310.894),
         "revived: Weakness applied"),
        ("Weakness", pytest.approx(310.894), pytest.approx(318.816), "death"),
        ("Dead", pytest.approx(318.816), pytest.approx(348.224),
         "revived: Brink of Death applied"),
        ("Brink of Death", pytest.approx(348.224), pytest.approx(441.36), "death"),
        ("Dead", pytest.approx(441.36), pytest.approx(451.07),
         "revived: Brink of Death applied"),
        ("Brink of Death", pytest.approx(451.07), pytest.approx(551.078), "expired"),
    ]
    brink = next(p for p in result.damage_penalties if p.name == "Brink of Death")
    assert brink.affected_hits == 429


def test_potted_weakness_dot_snapshot_survives_both_status_expiries(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight(ARCHIVE, "R3HNYA1yJkL8CWhV/fight-1/source-7/")
    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert result.unmatched == ()
    assert result.potion.uses == 1

    fight = json.loads((tmp_path / "fight.json").read_text())
    master = json.loads((tmp_path / "master-data.json").read_text())
    names = {ability["gameID"]: ability["name"] for ability in master["abilities"]}
    ticks = reconstruct_brd_dots(
        json.loads((tmp_path / "damage-events.json").read_text()), names, 7,
    )
    tick = next(
        t for t in ticks
        if t.name == "Stormbite" and t.timestamp - fight["startTime"] == 514_017
        and t.snapshot_timestamp is not None
        and t.snapshot_timestamp - fight["startTime"] == 488_754
    )
    assert tick.matched and tick.landed_fraction == 1
    assert {"1000043", "1000049"} <= set(tick.snapshot_buffs.split("."))
    # The live Weakness and potion windows ended at 512.193s and 500.541s;
    # the later tick retains both effects from its application snapshot.
    assert tick.timestamp > fight["startTime"] + 512_193
    profile = _load_combat_profile("bard")
    factor = lambda main_stat: 100 + 237 * (main_stat - 440) // 440
    expected = 25 * factor(7379 * 75 // 100) / factor(6838)
    assert brd_dot_potency(
        tick, 25, potion_multiplier=profile.player_potion_multiplier,
        self_buff_windows={}, combat_profile=profile,
    ) == pytest.approx(expected)
