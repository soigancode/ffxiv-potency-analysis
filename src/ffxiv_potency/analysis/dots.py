"""Match landed DoT ticks to target-specific applications and buff snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .damage import landed_fraction


@dataclass(frozen=True, slots=True)
class DotRules:
    names: frozenset[str]
    duration_ms: int
    refresh_action: str | None = None
    grace_ms: int = 3000


@dataclass(frozen=True, slots=True)
class DotTick:
    name: str
    timestamp: int
    target_id: int
    application_packet: int
    application_name: str
    snapshot_timestamp: int | None
    snapshot_buffs: str
    tick_buffs: str
    matched: bool
    landed_fraction: float = 1.0


def reconstruct_dot_ticks(
    damage: list[dict[str, Any]],
    ability_names: dict[int, str],
    source_id: int,
    rules: DotRules,
) -> tuple[DotTick, ...]:
    """Match each tick to a live application on the same target and instance.

    A refresh affects only existing DoTs on its target. A landed application
    supplies the snapshot buffs; periodic events retain its packet ID.
    """
    applications: dict[tuple[int, int, str], tuple[int, int, str, str]] = {}
    ticks: list[DotTick] = []
    timeline = [
        event
        for event in damage
        if event.get("sourceID") == source_id
        and isinstance(event.get("timestamp"), int)
        and event.get("type") == "damage"
    ]
    timeline.sort(key=lambda event: (event["timestamp"], bool(event.get("tick"))))
    for event in timeline:
        name = ability_names.get(event.get("abilityGameID"))
        target = event.get("targetID")
        instance = event.get("targetInstance", 0)
        packet = event.get("packetID")
        if not isinstance(target, int) or not isinstance(packet, int):
            continue
        timestamp = event["timestamp"]
        if event.get("tick") and name in rules.names:
            if event.get("amount") == 0 or event.get("hitType") == 10:
                continue
            key = (target, instance, name)
            application = applications.get(key)
            matched = bool(
                application
                and application[0] == packet
                and timestamp <= application[1] + rules.duration_ms + rules.grace_ms
            )
            ticks.append(
                DotTick(
                    name=name,
                    timestamp=timestamp,
                    target_id=target,
                    application_packet=packet,
                    application_name=application[2] if matched else "",
                    snapshot_timestamp=application[1] if matched else None,
                    snapshot_buffs=application[3] if matched else "",
                    tick_buffs=str(event.get("buffs", "")),
                    matched=matched,
                    landed_fraction=landed_fraction(event),
                )
            )
            continue
        if event.get("amount") == 0 or event.get("hitType") == 10:
            continue
        buffs = str(event.get("buffs", ""))
        if name in rules.names:
            applications[(target, instance, name)] = (packet, timestamp, name, buffs)
        elif rules.refresh_action is not None and name == rules.refresh_action:
            for dot_name in rules.names:
                key = (target, instance, dot_name)
                old = applications.get(key)
                if old and timestamp <= old[1] + rules.duration_ms + rules.grace_ms:
                    applications[key] = (packet, timestamp, name, buffs)
    return tuple(ticks)
