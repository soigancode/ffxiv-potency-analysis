"""Hand-audited event slice: FF Logs R86rXnMqjHTDJz3A fight 4 source 11.

For both Chain Saw and Excavator, each of the selected two-target packets
contributes 660 + 495 = 1155 before potions. The second packet of each occurs
during the recorded potion (player attack factor 615 -> 659). Air Anchor is
potted before pull, with its cast missing from the selected fight.
"""

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
