"""Hand-audited slice of FF Logs zYLAW7KTBk8P4XxG, fight 9, source 18.

Five landed Blazing Shots during Hypercharge: 5 * (240 + 20) potency.
Five weaponskill triggers before Wildfire resolves: 5 * 240 potency.
Six consecutive auto-attacks match a 2.64s weapon delay: their comparable
potency is 80 * 183 / 208 / 1.2 each; the last four carry Medicated. All five Blazing Shots and
Wildfire carry Medicated too. Player potion factor: 659 / 615.
"""

from pathlib import Path

import pytest

from ffxiv_potency.fflogs import analyze_saved_fight


def test_audited_wildfire_hypercharge_auto_attacks_and_three_potions(
    tmp_path: Path, machinist_actions: Path, load_audit
) -> None:
    load_audit("tyrant_audit.json")
    result = analyze_saved_fight(tmp_path, machinist_actions)
    by_name = {action.name: action for action in result.actions}

    blazing = by_name["Blazing Shot"]
    wildfire = by_name["Wildfire"]
    assert (blazing.uses, blazing.hits) == (5, 5)
    assert blazing.potency_min == blazing.potency_max == pytest.approx(5 * (240 + 20) * 659 / 615)
    assert (wildfire.uses, wildfire.hits) == (1, 1)
    assert wildfire.potency_min == wildfire.potency_max == pytest.approx(5 * 240 * 659 / 615)

    (shot,) = result.auto_attacks
    assert shot.hits == 6
    assert shot.weapon_delay_seconds == pytest.approx(2.64)
    comparable_shot = 80 * 183 / 208 / 1.2
    assert shot.potency_per_hit == pytest.approx(comparable_shot)
    assert shot.total_potency == pytest.approx(
        6 * comparable_shot + 4 * comparable_shot * (659 / 615 - 1)
    )

    assert result.potion.uses == 3
    assert [window.start_seconds for window in result.potion.windows] == pytest.approx(
        [3.968, 291.713, 596.305]
    )
    assert result.potion.potted_potency_min == pytest.approx(
        5 * 260 + 5 * 240 + 4 * comparable_shot
    )
    assert result.potion.gained_potency_min == pytest.approx(
        (5 * 260 + 5 * 240 + 4 * comparable_shot) * (659 / 615 - 1)
    )
    assert result.ghosted == ()
    assert result.unmatched == ()
