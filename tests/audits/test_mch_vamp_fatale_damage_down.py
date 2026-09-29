"""M9S Damage Down affects MCH actions and a Wildfire window."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight

ARCHIVE = "mch_vamp_fatale_damage_down.zip"
PREFIX = "mMv987bGDNWfJhxt/fight-4/source-47/"
ACTIONS = Path(__file__).parents[2] / "data/machinist/7.55/actions.json"


def test_vamp_fatale_damage_down_strength_and_refreshes(tmp_path: Path, extract_fight) -> None:
    extract_fight(ARCHIVE, PREFIX)
    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert result.encounter_id == 101
    assert result.unmatched == ()

    damage = json.loads((tmp_path / "damage-events.json").read_text())
    assert {event.get("multiplier") for event in damage
            if event.get("type") == "damage" and event.get("amount", 0) > 0
            and event.get("buffs") == "1002218."} == {1}
    assert {event.get("multiplier") for event in damage
            if event.get("type") == "damage" and event.get("amount", 0) > 0
            and event.get("buffs") == "1002911.1002218."} == {0.75}
    assert {event.get("multiplier") for event in damage
            if event.get("type") == "damage" and event.get("amount", 0) > 0
            and event.get("buffs") == "1002911.1002964.1002216.1000141."} == {0.8}

    window = next(w for w in result.status_windows if w.name == "Damage Down")
    assert window.start_seconds == pytest.approx(474.965)
    assert window.refresh_seconds == pytest.approx((481.87, 482.893, 487.704))
    assert window.end_seconds == pytest.approx(517.664)
    assert window.end_reason == "expired"
    penalty = next(p for p in result.damage_penalties if p.name == "Damage Down")
    assert penalty.multiplier == 0.75
    assert penalty.affected_hits == 49

    # Wildfire detonated inside the Damage Down window. Its per-window summary
    # must include the same penalty as the landed action potency.
    assert result.mch_wildfires[-1].potency == pytest.approx(900)
    assert next(action for action in result.actions if action.name == "Wildfire").potency_min == (
        pytest.approx(sum(window.potency for window in result.mch_wildfires))
    )
