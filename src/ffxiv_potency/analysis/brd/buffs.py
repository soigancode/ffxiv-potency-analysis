"""Track Bard's personal damage buffs, including Radiant Finale."""

from __future__ import annotations

from typing import Any

from ..buffs import self_damage_multiplier as _brd_self_multiplier
from .songs import SONGS

__all__ = ["_brd_self_multiplier", "brd_self_buff_windows"]

SELF_DAMAGE_BUFFS = {"Raging Strikes": 1.15, "Mage's Ballad": 1.01}


def brd_self_buff_windows(
    casts: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    ability_names: dict[int, str],
    source_id: int,
) -> dict[int, tuple[tuple[int, int, float], ...]]:
    """Build self-sourced damage buff windows, including Finale's Coda strength."""
    coda: set[str] = set()
    finale_strength: dict[int, float] = {}
    relevant_casts = sorted(
        (event for event in casts if event.get("sourceID") == source_id),
        key=lambda event: event.get("timestamp", 0),
    )
    for cast in relevant_casts:
        ability_id = cast.get("abilityGameID")
        name = ability_names.get(ability_id) if isinstance(ability_id, int) else None
        if name in SONGS:
            coda.add(name)
        elif name == "Radiant Finale":
            if coda:
                finale_strength[cast["packetID"]] = 1 + 0.02 * len(coda)
            coda.clear()

    active: dict[int, tuple[int, int, float]] = {}
    completed: dict[int, list[tuple[int, int, float]]] = {}
    for event in sorted(buffs, key=lambda item: item.get("timestamp", 0)):
        if event.get("sourceID") != source_id or event.get("targetID") != source_id:
            continue
        status_id = event.get("abilityGameID")
        if not isinstance(status_id, int):
            continue
        name = ability_names.get(status_id)
        if name not in SELF_DAMAGE_BUFFS and status_id != 1002964:
            continue
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, int):
            continue
        kind = event.get("type")
        if kind == "removebuff":
            previous = active.pop(status_id, None)
            if previous:
                completed.setdefault(status_id, []).append(
                    (previous[0], timestamp, previous[2])
                )
            elif name == "Raging Strikes":
                # Its 20s application can fall before the saved fight starts.
                completed.setdefault(status_id, []).append(
                    (timestamp - 20_000, timestamp, SELF_DAMAGE_BUFFS[name])
                )
        elif kind in ("applybuff", "refreshbuff"):
            duration = event.get("duration")
            end = timestamp + int(duration) if isinstance(duration, (int, float)) else timestamp
            packet_id = event.get("packetID")
            if status_id == 1002964:
                strength = finale_strength.get(packet_id) if isinstance(packet_id, int) else None
            elif name is not None:
                strength = SELF_DAMAGE_BUFFS[name]
            else:
                continue
            if strength is None:
                continue  # Coda is unknown; do not invent a buff strength.
            previous = active.get(status_id)
            if previous and previous[1] >= timestamp and previous[2] == strength:
                active[status_id] = (previous[0], max(end, previous[1]), strength)
            else:
                if previous:
                    completed.setdefault(status_id, []).append(previous)
                active[status_id] = (timestamp, end, strength)
    for status_id, window in active.items():
        completed.setdefault(status_id, []).append(window)
    return {status: tuple(windows) for status, windows in completed.items()}
