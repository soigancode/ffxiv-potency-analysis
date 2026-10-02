"""Convert FF Logs overkill records into the portion of a hit that landed."""

from typing import Any

from .events import _event_name


def landed_fraction(event: dict[str, Any]) -> float:
    """Return dealt damage / damage before overkill clipping."""
    amount = event.get("amount")
    overkill = event.get("overkill")
    if (
        isinstance(amount, (int, float))
        and amount > 0
        and isinstance(overkill, (int, float))
        and overkill > 0
    ):
        return amount / (amount + overkill)
    return 1.0


def falloff_primary_hits(
    packets: dict[tuple[Any, Any], list[dict[str, Any]]],
    actions: dict[str, dict[str, Any]],
    abilities: dict[int, str],
    critical_multiplier: float,
) -> dict[tuple[Any, Any], dict[str, Any]]:
    """Normalized damage separates full-potency hits at substantial AoE falloff."""
    result = {}
    for packet, hits in packets.items():
        action = actions.get(_event_name(hits[0], abilities), {})
        if not isinstance(action.get("potency"), dict) or not action["potency"].get("falloff"):
            continue

        def normalized_damage(hit: dict[str, Any]) -> float:
            crit = critical_multiplier if hit.get("hitType") == 2 else 1
            direct = 1.25 if hit.get("directHit") else 1
            multiplier = hit.get("multiplier", 1)
            if not isinstance(multiplier, (int, float)) or multiplier <= 0:
                return 0
            return (hit.get("amount", 0) + max(0, hit.get("overkill", 0))) / (
                crit * direct * multiplier
            )

        result[packet] = max(hits, key=normalized_damage)
    return result
