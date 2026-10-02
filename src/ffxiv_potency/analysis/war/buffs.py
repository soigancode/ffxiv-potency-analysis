"""Track Surging Tempest without counting the combo that first grants it."""

import re
from typing import Any

from ..buffs import damage_snapshot_times
from ..errors import AnalysisError
from ..events import _has_buff

SURGING_TEMPEST = 1002677
INNER_RELEASE = 1001177


def war_self_buff_windows(
    buffs: list[dict[str, Any]], actions: dict[str, dict[str, Any]],
    damage: list[dict[str, Any]], casts: list[dict[str, Any]],
    source_id: int, start: int, end: int,
) -> dict[int, tuple[tuple[int, int, float], ...]]:
    description = " ".join(actions.get("Storm's Eye", {}).get("description", ()))
    match = re.search(r"Grants Surging Tempest, increasing damage dealt by (\d+)%", description)
    if match is None:
        raise AnalysisError("cannot determine Surging Tempest strength from Warrior actions")
    strength = 1 + int(match[1]) / 100
    own = sorted(
        (event for event in buffs if event.get("abilityGameID") == SURGING_TEMPEST
         and event.get("sourceID") == source_id and event.get("targetID") == source_id),
        key=lambda event: event["timestamp"],
    )
    snapshots = damage_snapshot_times(damage, casts)
    boundary = own[0]["timestamp"] if own else end
    initial = False
    for event in damage:
        time = event.get("timestamp")
        if not isinstance(time, (int, float)) or event.get("sourceID") != source_id:
            continue
        snapshot = snapshots.get((event.get("packetID"), event.get("abilityGameID")), time)
        if _has_buff(event, SURGING_TEMPEST) and snapshot < boundary:
            initial = True
            break
    active = (start, end) if initial else None
    completed = []
    for event in own:
        time = event["timestamp"]
        if event["type"] == "removebuff":
            if active:
                completed.append((active[0], min(time, active[1]), strength))
                active = None
        elif event["type"] in {"applybuff", "refreshbuff"}:
            duration = event.get("duration")
            if not isinstance(duration, (int, float)) or not 0 < duration <= 60000:
                raise AnalysisError("Surging Tempest grant has no valid duration")
            if active:
                completed.append((active[0], min(time, active[1]), strength))
            active = (time, time + int(duration))
    if active:
        completed.append((active[0], min(active[1], end), strength))
    return {SURGING_TEMPEST: tuple(completed)}
