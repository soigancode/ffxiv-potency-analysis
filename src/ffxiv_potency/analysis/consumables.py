"""Identify the item that applied a food or potion status in FF Logs events."""

from typing import Any

from .models import ConsumableIdentity


def initial_food_aura(
    combatants: list[dict[str, Any]] | None, source_id: int | None, buff_id: int,
) -> bool | None:
    """Read the player's initial auras, if that snapshot is available."""
    if source_id is None or combatants is None:
        return None
    initial = next((event for event in combatants
                    if isinstance(event, dict) and event.get("sourceID") == source_id), None)
    auras = initial.get("auras") if initial is not None else None
    if not isinstance(auras, list):
        return None
    return any(isinstance(aura, dict) and aura.get("ability") == buff_id for aura in auras)


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
    fight_start: float, fight_end: float, *, initially_fed: bool | None = None,
) -> tuple[tuple[float, float], ...]:
    """Find unfed intervals from initial auras and subsequent food changes."""
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
        if source_id is not None and initially_fed is False:
            return ((fight_start, fight_end),)
        return ()  # An unavailable initial snapshot retains the configured assumption.
    # A removal or refresh also establishes a pre-pull aura if the initial
    # snapshot was absent or incomplete.
    active = initially_fed is True or changes[0][1] in {"removebuff", "refreshbuff"}
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
