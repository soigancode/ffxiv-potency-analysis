"""Normalize direct damage for comparisons between known and candidate potencies."""

from typing import Any

from .consumables import food_active
from .events import _has_buff
from .penalties import revival_multiplier
from .profiles import _CombatProfile


def normalized_damage(
    event: dict[str, Any],
    critical_multiplier: float,
    *,
    potion_multiplier: float = 1.0,
    potion_buff_id: int = 1000049,
    unfed_critical_multiplier: float | None = None,
    unfed_determination_ratio: float = 1.0,
    food_missing: tuple[tuple[float, float], ...] = (),
    combat_profile: _CombatProfile | None = None,
) -> float:
    amount = float(event["amount"])
    timestamp = event.get("timestamp")
    unfed = isinstance(timestamp, (int, float)) and not food_active(timestamp, food_missing)
    if event.get("hitType") == 2:
        amount /= (
            unfed_critical_multiplier
            if unfed and unfed_critical_multiplier is not None
            else critical_multiplier
        )
    if event.get("directHit") is True:
        amount /= 1.25
    # FF Logs includes raid buffs, target debuffs, and a 1.05 Medicated
    # contribution in this combined value. The actual main-stat factor
    # differs; remove that difference to compare with unpotted hits.
    multiplier = event.get("multiplier", 1.0)
    if isinstance(multiplier, (int, float)) and multiplier > 0:
        amount /= multiplier
        if _has_buff(event, potion_buff_id):
            amount *= 1.05 / potion_multiplier
        # FF Logs labels these as 0.75/0.50 in its multiplier, while the
        # main-stat damage formula produces a slightly different factor.
        # Remove the remaining difference for cross-window classification.
        if combat_profile is not None:
            for status_id, displayed in ((1000044, 0.50), (1000043, 0.75)):
                if _has_buff(event, status_id):
                    amount *= displayed / revival_multiplier(event, combat_profile)
                    break
    if unfed:
        amount *= unfed_determination_ratio
    return amount
