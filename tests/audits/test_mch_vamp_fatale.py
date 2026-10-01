"""Hand-audited expectations from FF Logs DFm9brj421X6T73k, fight 1, source 2.

The event fixture contains selected original records; damage amounts are deliberately
not used as expected potency. These expectations derive from the 7.5 job guide:

* Chain Saw: 660 (potted), 660 + 495 (two targets), 660 (immune cell + boss).
* Queen at 60 Battery: five 144 Arm Punches, 408 Pile Bunker, 468 Collider.
* Player potion: attack factor 620 -> 664; pet potion: 525 -> 563.
* Queen conversion: 0.89. The potion starts 30s before Medicated expires.
"""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight


def test_audited_vamp_fatale_events(tmp_path: Path, mch_actions: Path, load_audit) -> None:
    load_audit("mch_vamp_fatale_audit.json")
    result = analyze_saved_fight(tmp_path, mch_actions)
    by_name = {action.name: action for action in result.actions}

    # The selected log includes one potted single target, one double target,
    # and one immune cell followed by a landed boss hit.
    saw = by_name["Chain Saw"]
    assert (saw.uses, saw.hits) == (3, 4)
    assert (
        saw.potency_min
        == saw.potency_max
        == pytest.approx(660 * 3839 / 3547 + (660 + 660 * 0.75) + 660)
    )

    # Air Anchor, Chain Saw, and Excavator each grant 20 Battery before Queen.
    (queen,) = result.pet_deployments
    assert queen.gauge_spent == 60
    queen_base = 5 * 144 + 408 + 468
    assert queen.potency_min == queen.potency_max == pytest.approx(queen_base * 0.89 * 564 / 526)

    assert result.potion.uses == 1
    (window,) = result.potion.windows
    assert window.start_seconds == pytest.approx(-0.016)
    assert window.end_seconds == pytest.approx(29.984)
    # The three player skills and seven Queen hits all carry Medicated.
    assert result.potion.potted_potency_min == pytest.approx(3 * 660 + queen_base * 0.89)
    assert result.potion.gained_potency_min == pytest.approx(
        3 * 660 * (3839 / 3547 - 1) + queen_base * 0.89 * (564 / 526 - 1)
    )

    assert result.ghosted == (("Heated Slug Shot", 1),)
    assert result.ghosted_times == (("Heated Slug Shot", (67.904,)),)
    assert result.unmatched == ()


def test_audited_potency_ignores_damage_rolls_and_hit_outcomes(
    tmp_path: Path, mch_actions: Path, load_audit
) -> None:
    """Critical hits and damage amounts cannot change landed potency."""
    source = load_audit("mch_vamp_fatale_audit.json")
    before = analyze_saved_fight(tmp_path, mch_actions)
    for event in source["damage_events"]:
        if event.get("type") == "damage" and event.get("amount", 0) > 0:
            event["amount"] *= 3
            event["hitType"] = 2
            event["directHit"] = True
    (tmp_path / "damage-events.json").write_text(
        json.dumps(source["damage_events"]), encoding="utf-8"
    )
    after = analyze_saved_fight(tmp_path, mch_actions)
    assert after.potency_min == before.potency_min
    assert after.potion.gained_potency_min == before.potion.gained_potency_min
    assert after.luck_score != before.luck_score
