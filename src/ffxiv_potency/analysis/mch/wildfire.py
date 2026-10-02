"""Resolve Wildfire from landed weaponskills and its application snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from ..events import _event_name, _has_buff

if TYPE_CHECKING:
    from ..models import PotionWindow


@dataclass(frozen=True, slots=True)
class MchWildfireSummary:
    applied_seconds: float
    detonated_seconds: float | None
    landed_weaponskills: int
    potency: float
    detonated_early: bool = False
    contributing_actions: tuple[str, ...] = ()
    contributing_times: tuple[float, ...] = ()
    cast_seconds: float | None = None
    ended_seconds: float | None = None


@dataclass(slots=True)
class MchWildfireTracker:
    casts: list[dict[str, Any]]
    buffs: list[dict[str, Any]]
    names: dict[int, str]
    actions: dict[str, dict[str, Any]]
    landed_by_packet: dict[tuple[Any, Any], list[dict[str, Any]]]
    potion_windows: tuple[PotionWindow, ...]
    source_id: int | None
    fight_start: float
    fight_end: float
    potion_buff_id: int
    potion_multiplier: float
    applications: dict[int, float] = field(init=False)
    records: dict[int, MchWildfireSummary] = field(default_factory=dict)
    potted_events: set[int] = field(default_factory=set)
    explosion_casts: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.applications = {
            event["packetID"]: event["timestamp"]
            for event in self.buffs
            if event.get("type") == "applybuff"
            and _event_name(event, self.names) == "Wildfire"
            and event.get("sourceID") == self.source_id
            and event.get("targetID") == self.source_id
            and isinstance(event.get("packetID"), int)
            and isinstance(event.get("timestamp"), (int, float))
        }

    def application(self, cast: dict[str, Any]) -> float:
        packet_id = cast.get("packetID")
        timestamp = cast.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            raise TypeError("Wildfire cast has no valid timestamp")
        if isinstance(packet_id, int):
            return float(self.applications.get(packet_id, timestamp))
        return float(timestamp)

    def contributing_casts(self, started: float, finished: float) -> tuple[tuple[float, str], ...]:
        seen = set()
        actions = []
        for cast in sorted(self.casts, key=lambda cast: cast.get("timestamp", 0)):
            if self.source_id is not None and cast.get("sourceID") != self.source_id:
                continue
            packet = cast.get("packetID")
            name = _event_name(cast, self.names)
            if packet is None or packet in seen:
                continue
            if "weaponskill" not in str(self.actions.get(name, {}).get("type", "")).lower():
                continue
            if any(
                started < hit.get("timestamp", 0) <= finished
                for hit in self.landed_by_packet.get((packet, cast.get("abilityGameID")), [])
            ):
                seen.add(packet)
                actions.append((float(cast["timestamp"]), name))
        return tuple(actions)

    def landed_triggers(self, started: float, finished: float) -> int:
        return len(self.contributing_casts(started, finished))

    def window_end(self, started: float, finished: float) -> float:
        """Use expiry/removal or Detonator use, before delayed explosion damage."""
        endings = [started + 10000, self.fight_end]
        endings.extend(
            e["timestamp"] for e in self.buffs
            if e.get("type") == "removebuff" and _event_name(e, self.names) == "Wildfire"
            and e.get("sourceID") == self.source_id and e.get("targetID") == self.source_id
            and started <= e.get("timestamp", -1) <= finished
        )
        endings.extend(
            e["timestamp"] for e in self.casts
            if _event_name(e, self.names) == "Detonator"
            and e.get("sourceID") == self.source_id
            and started <= e.get("timestamp", -1) <= finished
        )
        return min(endings)

    def _snapshotted_potion(self, cast: dict[str, Any], explosion: dict[str, Any]) -> bool:
        timestamp = self.application(cast)
        if not isinstance(timestamp, (int, float)):
            return False
        seconds = (timestamp - self.fight_start) / 1000
        if _has_buff(cast, self.potion_buff_id) or any(
            window.start_seconds is not None
            and window.end_seconds is not None
            and window.start_seconds <= seconds < window.end_seconds
            for window in self.potion_windows
        ):
            return True
        # The pre-pull cast may be outside the selected fight. The explosion
        # retains its snapshot unless another potion started in between.
        explosion_seconds = (explosion.get("timestamp", timestamp) - self.fight_start) / 1000
        return _has_buff(explosion, self.potion_buff_id) and not any(
            window.start_seconds is not None and seconds < window.start_seconds <= explosion_seconds
            for window in self.potion_windows
        )

    def record(self, explosion: dict[str, Any], maximum: int, per_trigger: int) -> float | None:
        event_time = explosion.get("timestamp", 0)
        trigger_casts = [
            cast
            for cast in self.casts
            if _event_name(cast, self.names) == "Wildfire"
            and cast.get("timestamp", 0) <= event_time
        ]
        if not trigger_casts:
            return None
        cast = trigger_casts[-1]
        started = self.application(cast)
        contributing = self.contributing_casts(started, event_time)[:maximum]
        triggers = len(contributing)
        value = float(triggers * per_trigger)
        potted = self._snapshotted_potion(cast, explosion)
        if potted:
            self.potted_events.add(id(explosion))
        self.explosion_casts[id(explosion)] = id(cast)
        self.records[id(cast)] = MchWildfireSummary(
            (started - self.fight_start) / 1000,
            (event_time - self.fight_start) / 1000,
            triggers,
            value * (self.potion_multiplier if potted else 1),
            any(
                _event_name(other, self.names) == "Detonator"
                and started <= other.get("timestamp", -1) <= event_time
                and other.get("sourceID") == cast.get("sourceID")
                for other in self.casts
            ),
            tuple(name for _, name in contributing),
            tuple((time - self.fight_start) / 1000 for time, _ in contributing),
            (cast["timestamp"] - self.fight_start) / 1000,
            (self.window_end(started, event_time) - self.fight_start) / 1000,
        )
        return value

    def set_landed_potency(self, explosion: dict[str, Any], potency: float) -> None:
        """Keep the window summary equal to the fully adjusted landed action."""
        cast_id = self.explosion_casts.get(id(explosion))
        if cast_id is not None and cast_id in self.records:
            self.records[cast_id] = replace(self.records[cast_id], potency=potency)

    def summaries(self) -> tuple[MchWildfireSummary, ...]:
        rows = []
        for cast in self.casts:
            if (_event_name(cast, self.names) != "Wildfire"
                    or not isinstance(cast.get("timestamp"), (int, float))):
                continue
            existing = self.records.get(id(cast))
            if existing is not None:
                rows.append(existing)
                continue
            started = self.application(cast)
            contributing = self.contributing_casts(
                started, min(self.fight_end, started + 10000)
            )[:6]
            rows.append(MchWildfireSummary(
                (started - self.fight_start) / 1000, None, len(contributing), 0,
                contributing_actions=tuple(name for _, name in contributing),
                contributing_times=tuple((time - self.fight_start) / 1000 for time, _ in contributing),
                cast_seconds=(cast["timestamp"] - self.fight_start) / 1000,
                ended_seconds=(self.window_end(started, self.fight_end) - self.fight_start) / 1000,
            ))
        return tuple(rows)
