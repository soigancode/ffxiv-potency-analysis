"""Fight or Flight windows and Circle of Scorn application snapshots."""

import re
from typing import Any

from ..buffs import damage_snapshot_times
from ..dots import DotRules, reconstruct_dot_ticks
from ..errors import AnalysisError
from ..events import _has_buff

FIGHT_OR_FLIGHT = 1000076


def fight_or_flight_strength(actions) -> float:
    text = " ".join(actions.get("Fight or Flight", {}).get("description", ()))
    match = re.search(r"Increases damage dealt by (\d+)%", text)
    if match is None:
        raise AnalysisError("cannot determine Fight or Flight strength from Paladin actions")
    return 1 + int(match[1]) / 100


def pld_self_buff_windows(buffs, actions, damage, casts, combatants, source, start, end):
    strength = fight_or_flight_strength(actions)
    own = sorted((e for e in buffs if e.get("abilityGameID") == FIGHT_OR_FLIGHT
                  and e.get("sourceID") == source and e.get("targetID") == source),
                 key=lambda e: e["timestamp"])
    boundary = own[0]["timestamp"] if own else end
    times = damage_snapshot_times(damage, casts)
    initial = any(a.get("ability") == FIGHT_OR_FLIGHT for c in combatants
                  if c.get("sourceID") == source for a in c.get("auras", ())) or any(
        e.get("sourceID") == source and _has_buff(e, FIGHT_OR_FLIGHT)
        and e["timestamp"] < boundary
        and times.get((e.get("packetID"), e.get("abilityGameID")), e["timestamp"]) < boundary
        for e in damage)
    active = (start, end) if initial else None
    windows = []
    for e in own:
        time = e["timestamp"]
        if e["type"] == "removebuff":
            if active:
                # At this exact millisecond, explicit packet buff evidence can
                # still prove a snapshot before removal. No general grace window.
                windows.append((active[0], min(time, active[1]) + 1, strength))
                active = None
        elif e["type"] in {"applybuff", "refreshbuff"}:
            if active:
                windows.append((active[0], min(time, active[1]), strength))
            active = (time, time + e.get("duration", 20000))
    if active:
        windows.append((active[0], min(active[1], end), strength))
    return {FIGHT_OR_FLIGHT: tuple(windows)}


def circle_snapshots(damage: list[dict[str, Any]], casts: list[dict[str, Any]],
                     names: dict[int, str], source: int) -> dict[int, dict[str, Any]]:
    """Use shared target/instance tick matching and the application's cast time."""
    ticks = reconstruct_dot_ticks(damage, names, source,
                                  DotRules(frozenset({"Circle of Scorn"}), 15000))
    times = damage_snapshot_times(damage, casts)
    applications = {(e.get("packetID"), e.get("targetID")): e for e in damage
                    if e.get("type") == "damage" and not e.get("tick")
                    and isinstance(e.get("abilityGameID"), int)
                    and names.get(e["abilityGameID"]) == "Circle of Scorn"
                    and e.get("sourceID") == source}
    matched = {(t.timestamp, t.application_packet, t.target_id): t for t in ticks}
    snapshots = {}
    for e in damage:
        ability_id = e.get("abilityGameID")
        if (not e.get("tick") or not isinstance(ability_id, int)
                or names.get(ability_id) != "Circle of Scorn"):
            continue
        timestamp = e.get("timestamp")
        packet = e.get("packetID")
        target = e.get("targetID")
        tick = (matched.get((timestamp, packet, target))
                if isinstance(timestamp, int) and isinstance(packet, int)
                and isinstance(target, int) else None)
        if tick is None or not tick.matched:
            if e.get("amount", 0) > 0:
                raise AnalysisError("cannot match Circle of Scorn tick to a landed application")
            continue
        application = applications[e.get("packetID"), e.get("targetID")]
        snapshots[id(e)] = {**e, "buffs": application.get("buffs", ""),
                            "_snapshot_time": times.get(
                                (application.get("packetID"), application.get("abilityGameID")),
                                application["timestamp"])}
    return snapshots
