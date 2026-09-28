"""Resolve Wildfire from landed weaponskills and its application snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    def landed_triggers(self, started: float, finished: float) -> int:
        # Casts at application time still count when their damage lands afterwards.
        return len({
            cast.get("packetID")
            for cast in self.casts
            if cast.get("packetID") is not None
            and any(
                started < hit.get("timestamp", 0) <= finished
                for hit in self.landed_by_packet.get(
                    (cast.get("packetID"), cast.get("abilityGameID")), []
                )
            )
            and "weaponskill" in str(
                self.actions.get(_event_name(cast, self.names), {}).get("type", "")
            ).lower()
        })

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
            window.start_seconds is not None
            and seconds < window.start_seconds <= explosion_seconds
            for window in self.potion_windows
        )

    def record(self, explosion: dict[str, Any], maximum: int, per_trigger: int) -> float | None:
        event_time = explosion.get("timestamp", 0)
        trigger_casts = [
            cast for cast in self.casts
            if _event_name(cast, self.names) == "Wildfire"
            and cast.get("timestamp", 0) <= event_time
        ]
        if not trigger_casts:
            return None
        cast = trigger_casts[-1]
        started = self.application(cast)
        triggers = min(self.landed_triggers(started, event_time), maximum)
        value = float(triggers * per_trigger)
        potted = self._snapshotted_potion(cast, explosion)
        if potted:
            self.potted_events.add(id(explosion))
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
        )
        return value

    def summaries(self) -> tuple[MchWildfireSummary, ...]:
        return tuple(
            self.records.get(
                id(cast),
                MchWildfireSummary(
                    (self.application(cast) - self.fight_start) / 1000,
                    None,
                    min(self.landed_triggers(
                        self.application(cast), min(self.fight_end, self.application(cast) + 10000)
                    ), 6),
                    0,
                ),
            )
            for cast in self.casts
            if _event_name(cast, self.names) == "Wildfire"
            and isinstance(cast.get("timestamp"), (int, float))
        )
