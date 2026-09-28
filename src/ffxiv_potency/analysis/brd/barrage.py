"""Find Shadowbite packets empowered by a consumed Barrage buff."""

from __future__ import annotations

from typing import Any

from ..events import _event_name


def _barrage_shadowbite_packets(
    casts: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    names: dict[int, str],
    source_id: int,
) -> set[tuple[Any, Any]]:
    """Find Shadowbite casts that consume the Bard's Barrage status."""
    windows: list[tuple[float, float]] = []
    applied: float | None = None
    expires: float | None = None
    for event in sorted(buffs, key=lambda row: row.get("timestamp", 0)):
        ability_id = event.get("abilityGameID")
        if (event.get("sourceID") != source_id or event.get("targetID") != source_id
                or not isinstance(ability_id, int) or names.get(ability_id) != "Barrage"):
            continue
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            continue
        if event.get("type") in ("applybuff", "refreshbuff"):
            applied = timestamp
            duration = event.get("duration")
            expires = timestamp + duration if isinstance(duration, (int, float)) else timestamp + 10000
        elif event.get("type") == "removebuff" and applied is not None:
            windows.append((applied, timestamp))
            applied = expires = None
    if applied is not None and expires is not None:
        windows.append((applied, expires))
    return {
        (cast.get("packetID"), cast.get("abilityGameID"))
        for cast in casts
        if _event_name(cast, names) == "Shadowbite"
        and cast.get("sourceID") == source_id
        and cast.get("packetID") is not None
        and isinstance(cast.get("timestamp"), (int, float))
        and any(begin <= cast["timestamp"] <= finish for begin, finish in windows)
    }
