"""Encounter-wide damageable windows and the time denominator for potency rates."""

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class TargetableTime:
    seconds: float | None
    source: str
    intervals: tuple[tuple[float, float], ...] = ()


def targetable_intervals(
    events: list[dict[str, Any]],
    damage: list[dict[str, Any]],
    overkills: list[dict[str, Any]],
    actors: dict[int, dict[str, Any]],
    start: float,
    end: float,
) -> tuple[tuple[float, float], ...]:
    """Union enemy instances, preserving overlapping targets and repeated NPC IDs.

    A hostile hit establishes an initial enemy presence. Subsequent attack gaps
    never close a window. Closures require targetability, death, or lethal-hit
    evidence. Initial bosses are present from pull, later unknown appearances
    begin at their first encounter-wide hit.
    """

    def enemy(actor_id: Any) -> bool:
        actor = actors.get(actor_id, {})
        return actor.get("type") == "NPC" and actor.get("petOwner") is None

    def key(event: dict[str, Any], field: str) -> tuple[Any, Any]:
        return event.get(field + "ID"), event.get(field + "Instance", 1)

    appearances: dict[tuple[Any, Any], float] = {}
    for event in damage:
        if (
            event.get("type") in {"damage", "calculateddamage"}
            and event.get("amount", 0) > 0
            and enemy(event.get("targetID"))
        ):
            target = key(event, "target")
            appearances[target] = min(appearances.get(target, end), event["timestamp"])
    timeline: dict[tuple[Any, Any], list[tuple[float, int]]] = {}
    for event in events:
        if event.get("type") == "targetabilityupdate" and enemy(event.get("sourceID")):
            target = key(event, "source")
            timeline.setdefault(target, []).append(
                (event["timestamp"], int(event.get("targetable", 0)))
            )
        elif event.get("type") == "death" and enemy(event.get("targetID")):
            timeline.setdefault(key(event, "target"), []).append((event["timestamp"], 0))
    for event in overkills:
        if enemy(event.get("targetID")) and event.get("overkill", 0) > 0:
            timeline.setdefault(key(event, "target"), []).append((event["timestamp"], 0))
    initial_hit = min(appearances.values(), default=end)
    intervals = []
    for target in appearances.keys() | timeline.keys():
        updates = sorted(set(timeline.get(target, [])))
        first = appearances.get(target)
        opened = (
            start
            if updates and updates[0][1] == 0 and actors.get(target[0], {}).get("subType") == "Boss"
            else None
        )
        if first is not None and not any(time <= first and state == 1 for time, state in updates):
            opened = start if first == initial_hit else max(start, first)
        for time, state in updates:
            if state == 1 and opened is None:
                opened = max(start, time)
            elif state == 0 and opened is not None:
                if time > opened:
                    intervals.append((opened, min(end, time)))
                opened = None
        if opened is not None and opened < end:
            intervals.append((opened, end))
    merged: list[tuple[float, float]] = []
    for begin, finish in sorted(intervals):
        if finish <= begin:
            continue
        if merged and begin <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(finish, merged[-1][1])
        else:
            merged.append((begin, finish))
    return tuple(merged)


def resolve_targetable_time(
    fight: dict[str, Any],
    actors: dict[int, dict[str, Any]],
    damage: list[dict[str, Any]],
    events: list[dict[str, Any]],
    overkills: list[dict[str, Any]],
    dps: float | None,
    encounter_damage: list[dict[str, Any]] | None = None,
) -> TargetableTime:
    start, end = float(fight["startTime"]), float(fight["endTime"])
    elapsed = (end - start) / 1000
    intervals = targetable_intervals(
        events, encounter_damage if encounter_damage is not None else damage, overkills, actors, start, end
    )
    observed = sum(finish - begin for begin, finish in intervals) / 1000
    # Rankings supply the exact encounter DPS denominator for supported raid,
    # trial kills. Never use nDPS/rDPS as the damage divisor.
    # Complete dungeon and Criterion runs can keep travel time in their rankings and need the enemy timeline.
    if fight.get("encounterID") not in {4549, 4550, 4551} and dps and dps > 0:
        total = sum(e.get("amount", 0) for e in damage if e.get("type") == "damage")
        inferred = total / dps
        consistent = not intervals or abs(inferred - observed) <= max(2.0, elapsed * 0.05)
        if isfinite(inferred) and elapsed * 0.5 <= inferred <= elapsed + 0.05 and consistent:
            return TargetableTime(min(inferred, elapsed), "FF Logs DPS duration", intervals)
    if encounter_damage is not None and intervals:
        return TargetableTime(
            observed, "encounter enemy timeline (estimated spawn times)", intervals
        )
    if events and intervals:
        return TargetableTime(observed, "targetability timeline (estimated spawn times)", intervals)
    return TargetableTime(None, "unavailable (PPS uses full fight duration)")
