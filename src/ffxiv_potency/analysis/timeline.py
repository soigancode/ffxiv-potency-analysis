"""Select a verified encounter timeline without rewriting downloaded metadata."""

from math import isfinite
from typing import Any


def combat_timeline(fight: dict[str, Any], context: dict[str, Any] | None = None
                    ) -> tuple[dict[str, Any], float | None]:
    """AMT's combat duration establishes the website origin after dungeon start.

    Other dungeons retain their saved start. Research metadata is usable only
    when it describes the same fight and original time range.
    """
    if fight.get("encounterID") != 4550:
        return fight, None
    start, end = fight.get("startTime"), fight.get("endTime")
    if (not isinstance(start, (int, float)) or isinstance(start, bool) or not isfinite(start)
            or not isinstance(end, (int, float)) or isinstance(end, bool) or not isfinite(end)
            or end <= start):
        return fight, None
    combat = fight.get("combatTime")
    if "combatTime" not in fight and context is not None:
        recorded = context.get("fight")
        if isinstance(recorded, dict) and all(
            recorded.get(key) == fight.get(key)
            for key in ("id", "encounterID", "startTime", "endTime")
        ):
            combat = recorded.get("combatTime")
    if (not isinstance(combat, (int, float)) or isinstance(combat, bool)
            or not isfinite(combat) or not 0 < combat <= end - start):
        return fight, None
    origin = end - combat
    return {**fight, "startTime": origin}, (origin - start) / 1000
