"""Resolve Dancer AoE targets and summarize actual dance-finish casts."""

from typing import Any

from ..events import _event_name
from ..models import DncFinishSummary


def dnc_primary_hits(
    packets: dict[tuple[Any, Any], list[dict[str, Any]]],
    actions: dict[str, dict[str, Any]],
    abilities: dict[int, str],
    critical_multiplier: float,
) -> dict[tuple[Any, Any], dict[str, Any]]:
    """At 40%/25% falloff, normalized damage separates the full-potency hit."""
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


def summarize_dnc_finishes(
    casts: list[dict[str, Any]],
    actions: dict[str, dict[str, Any]],
    abilities: dict[int, str],
    source_id: int | None,
    start: float,
    totals: dict[tuple[Any, Any], list[float]],
) -> tuple[DncFinishSummary, ...]:
    summaries = []
    for cast in casts:
        name = _event_name(cast, abilities)
        action = actions.get(name, {})
        if cast.get("sourceID") != source_id or not action.get("damage_buff"):
            continue
        hits, potency = totals.get((cast.get("packetID"), cast.get("abilityGameID")), [0, 0])
        summaries.append(
            DncFinishSummary(
                (cast["timestamp"] - start) / 1000,
                name,
                action.get("completed_steps"),
                int(hits),
                potency,
            )
        )
    return tuple(summaries)
