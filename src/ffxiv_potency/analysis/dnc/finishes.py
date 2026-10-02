"""Resolve Dancer AoE targets and summarize actual dance-finish casts."""

from typing import Any

from ..events import _event_name
from ..models import DncFinishSummary


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
