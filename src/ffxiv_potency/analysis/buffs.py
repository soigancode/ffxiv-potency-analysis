"""Apply only the selected player's own damage buffs to personal potency."""

from typing import Any


def self_damage_multiplier(
    buffs: str,
    timestamp: float,
    windows: dict[int, tuple[tuple[int, int, float], ...]],
) -> float:
    present = {int(value) for value in buffs.strip(".").split(".") if value.isdigit()}
    multiplier = 1.0
    for buff_id, intervals in windows.items():
        if buff_id in present:
            for start, end, strength in intervals:
                if start <= timestamp < end:
                    multiplier *= strength
                    break
    return multiplier


def damage_snapshot_times(
    damage: list[dict[str, Any]],
    casts: list[dict[str, Any]],
) -> dict[tuple[Any, Any], float]:
    """Resolve direct-hit snapshot times before their delayed landed records."""
    times = {
        (e.get("packetID"), e.get("abilityGameID")): float(e["timestamp"])
        for e in damage
        if e.get("type") == "calculateddamage"
        and isinstance(e.get("timestamp"), (int, float))
        and e.get("packetID") is not None
    }
    times.update(
        {
            (e.get("packetID"), e.get("abilityGameID")): float(e["timestamp"])
            for e in casts
            if isinstance(e.get("timestamp"), (int, float)) and e.get("packetID") is not None
        }
    )
    return times
