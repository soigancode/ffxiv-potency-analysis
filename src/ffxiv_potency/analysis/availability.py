"""Recorded encounter action locks and cooldown availability windows."""

from collections.abc import Sequence
from typing import Any

from .targetability import TargetableTime


def cooldown_availability(action: dict[str, Any], targetable: TargetableTime,
                          locks: tuple[tuple[float, float], ...], start: float,
                          end: float) -> tuple[tuple[float, float], ...] | None:
    """Share the same action eligibility for opportunity and timing reports."""
    if action.get("potency") is None:
        return available_windows(((start, end),), locks, start, end)
    if not targetable.intervals and targetable.seconds != 0:
        return None
    return available_windows(targetable.intervals, locks, start, end)


def action_lock_windows(debuffs: Sequence[dict[str, Any]], combatants: Sequence[dict[str, Any]],
                        names: dict[int, str], source: int, start: float,
                        end: float) -> tuple[tuple[float, float], ...]:
    """Down for the Count prevents actions while cooldowns continue recovering.

    Deaths and ordinary damage penalties do not shorten opportunity estimates.
    Missing opening applications can be bounded by their first removal.
    """
    def locked(status):
        return isinstance(status, int) and (
            status == 1000774 or names.get(status) == "Down for the Count")

    events = sorted((e for e in debuffs if e.get("targetID") == source
                     and locked(e.get("abilityGameID"))
                     and e.get("type") in {"applydebuff", "refreshdebuff", "removedebuff"}),
                    key=lambda e: e["timestamp"])
    initial = any(locked(a.get("ability")) for c in combatants
                  if c.get("sourceID") == source for a in c.get("auras", ()))
    active = start if initial or (events and events[0]["type"] == "removedebuff") else None
    expiry = end
    windows = []
    for event in events:
        time = event["timestamp"]
        if active is not None and time >= expiry:
            windows.append((active, expiry))
            active = None
        if event["type"] == "removedebuff":
            if active is not None:
                windows.append((active, time))
                active = None
        else:
            active = time if active is None else active
            duration = event.get("duration")
            expiry = min(end, time + duration) if isinstance(duration, (int, float)) else end
    if active is not None:
        windows.append((active, expiry))
    return tuple((max(start, a), min(end, b)) for a, b in windows
                 if min(end, b) > max(start, a))


def available_windows(windows: tuple[tuple[float, float], ...],
                      locks: tuple[tuple[float, float], ...], start: float,
                      end: float) -> tuple[tuple[float, float], ...]:
    """Clip availability to the fight and subtract recorded action locks."""
    pieces = [(max(start, a), min(end, b)) for a, b in windows
              if min(end, b) > max(start, a)]
    for low, high in locks:
        pieces = [(x, y) for a, b in pieces
                  for x, y in ((a, min(b, low)), (max(a, high), b)) if y > x]
    return tuple(pieces)
