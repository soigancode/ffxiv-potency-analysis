"""Infer potion windows including pre-pull applications."""

from __future__ import annotations

from typing import Any

from .events import _event_name, _has_buff
from .models import PotionWindow
from .profiles import _CombatProfile


def _potion_windows(
    casts: list[dict[str, Any]],
    landed: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    ability_names: dict[int, str],
    profile: _CombatProfile,
    fight_start: float,
    fight_end: float,
    source_id: int | None,
    snapshot_extension_ms: int = 0,
) -> tuple[PotionWindow, ...]:
    """Recover pre-pull potion windows using removal events when available."""
    cast_times = [
        cast.get("timestamp")
        for cast in casts
        if _event_name(cast, ability_names) in profile.potion_action_names
    ]
    cast_times = sorted(time for time in cast_times if isinstance(time, (int, float)))
    duration_ms = profile.potion_duration_seconds * 1000
    removals = sorted(
        event["timestamp"]
        for event in buffs
        if event.get("type") in ("removebuff", "removebuffstack")
        and event.get("abilityGameID")
        in (profile.potion_buff_id, profile.potion_buff_id % 1_000_000)
        and event.get("targetID") == source_id
        and isinstance(event.get("timestamp"), (int, float))
    )
    potted_times = sorted(
        event["timestamp"]
        for event in landed
        if _has_buff(event, profile.potion_buff_id)
        and isinstance(event.get("timestamp"), (int, float))
    )
    clusters: list[list[float]] = []
    for timestamp in potted_times:
        if not clusters or timestamp - clusters[-1][0] >= duration_ms:
            clusters.append([])
        clusters[-1].append(timestamp)
    windows = []
    for cast in cast_times:
        # The cast can precede buff application; a self-removal records the
        # observed end more accurately than cast time plus the nominal duration.
        removal = next(
            (time for time in removals if cast <= time <= cast + duration_ms + 3000),
            None,
        )
        end = removal if removal is not None else cast + duration_ms
        windows.append(
            PotionWindow(
                (cast - fight_start) / 1000,
                (min(fight_end, end) - fight_start) / 1000,
            )
        )
    for cluster in clusters:
        first, last = cluster[0], cluster[-1]
        # Snapshot damage can land after the buff expires; it is still part of
        # the original potion window, including when the damage forms a new cluster.
        if any(0 <= first - cast <= duration_ms + snapshot_extension_ms + 3000
               for cast in cast_times):
            continue
        if any(0 <= first - time <= snapshot_extension_ms + 3000 for time in removals):
            continue
        # A damage event can retain its snapshot buff just after removal.
        removal = next(
            (
                time
                for time in removals
                if first <= time <= first + duration_ms and last <= time + 2000
            ),
            None,
        )
        start = removal - duration_ms if removal is not None else None
        windows.append(
            PotionWindow(
                (start - fight_start) / 1000 if start is not None else None,
                (removal - fight_start) / 1000 if removal is not None else None,
                (first - fight_start) / 1000,
                (last - fight_start) / 1000,
                inferred=True,
            )
        )
    return tuple(
        sorted(
            windows,
            key=lambda window: (
                window.start_seconds
                if window.start_seconds is not None
                else window.observed_start_seconds or 0
            ),
        )
    )


