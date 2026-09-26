"""Hand-audited event slice: FF Logs R86rXnMqjHTDJz3A fight 4 source 11.

For both Chain Saw and Excavator, each of the selected two-target packets
contributes 660 + 495 = 1155 before potions. The second packet of each occurs
during the recorded potion (player attack factor 615 -> 659). Air Anchor is
potted before pull, with its cast missing from the selected fight.
"""

import json
from pathlib import Path

import pytest

from ffxiv_potency.fflogs import analyze_saved_fight


def test_audited_two_boss_fight_and_missing_prepull_cast(
    tmp_path: Path, machinist_actions: Path, load_audit
) -> None:
    load_audit("red_hot_deep_blue_audit.json")
    result = analyze_saved_fight(tmp_path, machinist_actions)
    by_name = {action.name: action for action in result.actions}

    for name in ("Chain Saw", "Excavator"):
        action = by_name[name]
        assert (action.uses, action.hits) == (2, 4)
        assert (
            action.potency_min == action.potency_max == pytest.approx((660 + 495) * (1 + 659 / 615))
        )
    assert by_name["Air Anchor"].potency_min == pytest.approx(660 * 659 / 615)

    assert result.potion.uses == 2
    opening, later = result.potion.windows
    assert opening.start_seconds is None  # No removal event in this saved fight.
    assert opening.observed_start_seconds == pytest.approx(1.698)
    assert later.start_seconds == pytest.approx(394.006)
    assert later.end_seconds == pytest.approx(424.006)
    assert result.potion.potted_potency_min == pytest.approx(660 + 2 * (660 + 495))
    assert result.potion.gained_potency_min == pytest.approx(
        (660 + 2 * (660 + 495)) * (659 / 615 - 1)
    )

    assert result.ghosted_times == (
        ("Heated Clean Shot", (339.037,)),
        ("Heated Slug Shot", (106.465,)),
    )
    assert result.unmatched == ()


def test_real_flamethrower_counts_zero_hit_cast_and_landed_ticks(
    tmp_path: Path, machinist_actions: Path, extract_fight
) -> None:
    extract_fight("red_hot_deep_blue_full.zip", "R86rXnMqjHTDJz3A/fight-4/source-11/")
    result = analyze_saved_fight(tmp_path, machinist_actions)
    flamethrower = next(action for action in result.actions if action.name == "Flamethrower")
    assert (flamethrower.uses, flamethrower.hits) == (2, 14)
    assert flamethrower.potency_min == flamethrower.potency_max == 14 * 120
    assert ("Flamethrower", 1) in result.ghosted
    assert ("Flamethrower", (172.534,)) in result.ghosted_times

    master = json.loads((tmp_path / "master-data.json").read_text(encoding="utf-8"))
    names = {item["gameID"]: item["name"] for item in master["abilities"]}
    casts = json.loads((tmp_path / "cast-events.json").read_text(encoding="utf-8"))
    damage = json.loads((tmp_path / "damage-events.json").read_text(encoding="utf-8"))
    flamethrower_casts = [e for e in casts if names.get(e.get("abilityGameID")) == "Flamethrower"]
    landed_ticks = [
        e
        for e in damage
        if e.get("type") == "damage" and names.get(e.get("abilityGameID")) == "Flamethrower"
    ]
    assert len(flamethrower_casts) == 2
    assert all(e["timestamp"] > flamethrower_casts[1]["timestamp"] for e in landed_ticks)


def test_dance_partner_devilment_adjusts_luck_only(
    tmp_path: Path, machinist_actions: Path, extract_fight
) -> None:
    extract_fight("red_hot_deep_blue_full.zip", "R86rXnMqjHTDJz3A/fight-4/source-11/")
    original = analyze_saved_fight(tmp_path, machinist_actions)
    events_path = tmp_path / "damage-events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    affected = [event for event in events if "1001825." in event.get("buffs", "")]
    assert affected
    for event in events:
        if "buffs" in event:
            event["buffs"] = event["buffs"].replace("1001825.", "")
    events_path.write_text(json.dumps(events), encoding="utf-8")
    without_devilment = analyze_saved_fight(tmp_path, machinist_actions)

    assert original.luck_score == without_devilment.luck_score
    assert original.adjusted_luck_score < without_devilment.adjusted_luck_score
