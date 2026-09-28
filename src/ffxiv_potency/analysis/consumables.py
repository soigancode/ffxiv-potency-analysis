"""Identify the item that applied a food or potion status in FF Logs events."""

from typing import Any

from .models import ConsumableIdentity


def identify_consumable(
    buffs: list[dict[str, Any]],
    casts: list[dict[str, Any]],
    ability_names: dict[int, str],
    source_id: int | None,
    buff_id: int,
    configured_name: str,
    *,
    cast_names: tuple[str, ...] = (),
) -> ConsumableIdentity:
    if source_id is None:
        return ConsumableIdentity(configured_name, recorded=False)
    names = dict.fromkeys(
        ability_names[event["extraAbilityGameID"]]
        for event in buffs
        if isinstance(event, dict)
        and event.get("type") in ("applybuff", "refreshbuff")
        and event.get("targetID") == source_id
        and event.get("abilityGameID") == buff_id
        and isinstance(event.get("extraAbilityGameID"), int)
        and event["extraAbilityGameID"] in ability_names
    )
    if names:
        return ConsumableIdentity(", ".join(names), recorded=True)
    for event in casts:
        ability_id = event.get("abilityGameID")
        if (
            isinstance(event, dict)
            and event.get("sourceID") == source_id
            and isinstance(ability_id, int)
            and ability_names.get(ability_id) in cast_names
        ):
            return ConsumableIdentity(ability_names[ability_id], recorded=True)
    return ConsumableIdentity(configured_name, recorded=False)


def food_gaps(
    buffs: list[dict[str, Any]], source_id: int | None, buff_id: int,
    fight_start: float, fight_end: float,
) -> tuple[tuple[float, float], ...]:
    """Find intervals without food; pre-pull food is inferred from its removal."""
    changes = sorted((
        (
            event["timestamp"], event["type"]
        )
        for event in buffs
        if isinstance(event, dict)
        and event.get("targetID") == source_id
        and event.get("abilityGameID") == buff_id
        and event.get("type") in {"applybuff", "refreshbuff", "removebuff"}
        and isinstance(event.get("timestamp"), (int, float))
        and fight_start <= event["timestamp"] <= fight_end
    ), key=lambda change: change[0])
    if not changes or source_id is None:
        return ()  # No recorded change: retain the configured food assumption.
    active = changes[0][1] in {"removebuff", "refreshbuff"}
    gap_start = fight_start if not active else None
    gaps = []
    for timestamp, kind in changes:
        if kind == "removebuff":
            if active:
                gap_start = timestamp
            active = False
        else:
            if not active and gap_start is not None and timestamp > gap_start:
                gaps.append((gap_start, timestamp))
            gap_start = None
            active = True
    if not active and gap_start is not None and gap_start < fight_end:
        gaps.append((gap_start, fight_end))
    return tuple(gaps)


def food_active(timestamp: float, gaps: tuple[tuple[float, float], ...]) -> bool:
    return not any(start <= timestamp < end for start, end in gaps)
