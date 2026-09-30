"""Battery gains use recorded action resolution, including ghosted damage."""

from collections import defaultdict
from typing import Any


def mch_battery_events(
    damage: list[dict[str, Any]], source_id: int | None,
) -> dict[tuple[Any, Any], list[dict[str, Any]]]:
    """Keep positive calculated and landed hits as evidence for Battery gains.

    A ghosted hit can resolve its gauge effect before the target disappears.
    These records are resource evidence only; they do not credit landed potency.
    """
    packets: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for event in damage:
        if (isinstance(event, dict) and event.get("sourceID", source_id) == source_id
                and event.get("type") in {"damage", "calculateddamage"}
                and event.get("hitType") != 10
                and isinstance(event.get("amount"), (int, float))
                and event["amount"] > 0 and event.get("packetID") is not None):
            packets[(event["packetID"], event.get("abilityGameID"))].append(event)
    return packets
