"""Read direct, combo, gauge and target falloff potency from an action."""

from __future__ import annotations

from typing import Any


def _direct_potency(
    action: dict[str, Any],
    event: dict[str, Any],
    *,
    is_primary_target: bool,
    modifier_bonus: int = 0,
    source_multiplier: float = 1.0,
    gauge_spent: int | None = None,
    gauge_minimum: int | None = None,
    gauge_maximum: int | None = None,
    base_potency_override: int | None = None,
) -> tuple[float, float] | None:
    potency = action.get("potency")
    if not isinstance(potency, dict):
        return None

    if event.get("tick"):
        dot = potency.get("damage_over_time")
        if isinstance(dot, dict) and isinstance(dot.get("potency_per_tick"), int):
            value = float(dot["potency_per_tick"])
            return value * source_multiplier, value * source_multiplier
        triggered = potency.get("triggered")
        if isinstance(triggered, dict):
            # Triggered actions such as Wildfire are resolved separately.
            return None

    value = potency.get("base")
    if base_potency_override is not None:
        value = base_potency_override
    combo = potency.get("combo")
    combo_bonus = event.get("bonusPercent")
    if isinstance(combo_bonus, (int, float)) and combo_bonus > 0 and isinstance(combo, dict):
        value = combo.get("potency", value)
    if not isinstance(value, int):
        return None

    minimum = maximum = float(value + modifier_bonus)
    scaling = potency.get("gauge_scaling")
    if isinstance(scaling, dict) and isinstance(scaling.get("maximum_potency"), int):
        scaling_maximum = float(scaling["maximum_potency"])
        if (
            gauge_spent is not None
            and gauge_minimum is not None
            and gauge_maximum is not None
            and gauge_maximum > gauge_minimum
        ):
            progress = (gauge_spent - gauge_minimum) / (gauge_maximum - gauge_minimum)
            minimum = maximum = minimum + (scaling_maximum - minimum) * progress
        else:
            maximum = scaling_maximum

    falloff = potency.get("falloff")
    if not is_primary_target and isinstance(falloff, dict):
        multiplier = falloff.get("additional_target_multiplier")
        if isinstance(multiplier, (int, float)):
            minimum *= multiplier
            maximum *= multiplier
    return minimum * source_multiplier, maximum * source_multiplier


def _is_channeled_action(action: dict[str, Any]) -> bool:
    description = " ".join(action.get("description", ())).casefold()
    return "effect ends upon using another action or moving" in description
