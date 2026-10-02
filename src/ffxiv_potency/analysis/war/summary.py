"""Warrior execution summaries from visible casts, ready effects, and landed hits."""

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from ..events import _event_name
from ..targetability import TargetableTime


@dataclass(frozen=True, slots=True)
class WarReadySummary:
    name: str
    grants: int
    uses: int
    expired: int
    overwritten: int
    remaining: int
    unconfirmed: int
    losses: tuple[tuple[float, str], ...] = ()


@dataclass(frozen=True, slots=True)
class WarTomahawk:
    seconds: float
    previous: str | None
    previous_gap: float | None
    following: str | None
    following_gap: float | None
    gaps: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class WarSummary:
    tempest_uptime: float | None
    tempest_targetable_seconds: float | None
    tempest_hits: int
    total_hits: int
    tempest_missing: tuple[tuple[float, str], ...]
    tempest_lost_potency: float
    inner_release_uses: int
    guaranteed_spenders: int
    unused_expired_charges: int
    ready: tuple[WarReadySummary, ...]
    infuriate_uses: int
    tomahawks: tuple[WarTomahawk, ...]
    expired_charges: tuple[tuple[float, int], ...] = ()


READY = (
    (1002624, "Primal Rend", ("Primal Rend",)),
    (1003834, "Primal Ruination", ("Primal Ruination",)),
    (1003901, "Primal Wrath", ("Primal Wrath",)),
    (1001897, "Nascent Chaos", ("Inner Chaos", "Chaotic Cyclone")),
)


def _tempest_setup_windows(
    casts: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    names: dict[int, str],
    actions: dict[str, dict[str, Any]],
    initial: set[Any],
    start: float,
    end: float,
    targetable: TargetableTime,
    windows: dict[int, tuple[tuple[int, int, float], ...]],
) -> list[tuple[float, float]]:
    """Exempt one required combo and its autos at pull or confirmed downtime expiry."""
    contexts = [start] if 1002677 not in initial else []
    tempest = windows.get(1002677, ())
    grants = sorted(
        (
            e
            for e in buffs
            if e.get("abilityGameID") == 1002677 and e.get("type") in {"applybuff", "refreshbuff"}
        ),
        key=lambda e: e["timestamp"],
    )
    for (_, gap_start), (gap_end, _) in zip(targetable.intervals, targetable.intervals[1:]):
        for _, finish, _ in tempest:
            if not gap_start < finish <= gap_end:
                continue
            grant = next((e for e in reversed(grants) if e["timestamp"] < finish), None)
            if grant is not None and isinstance(grant.get("duration"), (int, float)):
                expiry = grant["timestamp"] + grant["duration"]
                if abs(expiry - finish) <= 100:
                    contexts.append(gap_end)
    # Opening warnings start only after the first application, even when
    # free spenders precede the combo. Reopeners need confirmed natural expiry.
    return [
        (context, min((begin for begin, _, _ in tempest if begin >= context), default=end))
        for context in contexts
    ]


def _ready_summary(
    status: int,
    name: str,
    consumers: tuple[str, ...],
    casts: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    initial: bool,
    names: dict[int, str],
    start: float,
    end: float,
) -> WarReadySummary:
    grants = int(initial)
    uses = expired = overwritten = unconfirmed = 0
    active = initial
    expiry = None
    consumed_at = None
    losses = []
    timeline = [
        (e["timestamp"], 1, e)
        for e in buffs
        if e.get("abilityGameID") == status
        and e.get("type") in {"applybuff", "refreshbuff", "removebuff"}
    ]
    timeline += [(e["timestamp"], 0, e) for e in casts if _event_name(e, names) in consumers]
    for time, _, event in sorted(timeline, key=lambda row: row[:2]):
        if active and expiry is not None and time > expiry:
            expired += 1
            losses.append(((expiry - start) / 1000, "expired"))
            active = False
        if event["type"] == "cast":
            uses += 1
            if active:
                active = False
                consumed_at = time
        elif event["type"] in {"applybuff", "refreshbuff"}:
            overwritten += int(active)
            if active:
                losses.append(((time - start) / 1000, "overwritten"))
            grants += 1
            active = True
            duration = event.get("duration")
            expiry = time + duration if isinstance(duration, (int, float)) else None
            consumed_at = None
        elif active:
            # Cast resolution and removal can be slightly separated in FF Logs.
            near_cast = any(
                abs(c["timestamp"] - time) <= 1000 and _event_name(c, names) in consumers
                for c in casts
            )
            if not near_cast and expiry is not None and time >= expiry - 100:
                expired += 1
                losses.append(((time - start) / 1000, "expired"))
            elif not near_cast and consumed_at is None:
                unconfirmed += 1
            active = False
    if active and expiry is not None and expiry < end:
        expired += 1
        losses.append(((expiry - start) / 1000, "expired"))
        active = False
    return WarReadySummary(
        name, grants, uses, expired, overwritten, int(active), unconfirmed, tuple(losses)
    )


def summarize_war(
    casts: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    combatants: list[dict[str, Any]],
    names: dict[int, str],
    actions: dict[str, dict[str, Any]],
    source: int,
    start: float,
    end: float,
    hit_rows: list[tuple[float, str, float, float]],
    targetable_time: TargetableTime,
    windows: dict[int, tuple[tuple[int, int, float], ...]],
) -> WarSummary:
    own_casts = sorted(
        (e for e in casts if e.get("sourceID") == source), key=lambda e: e["timestamp"]
    )
    own_buffs = [e for e in buffs if e.get("sourceID") == source and e.get("targetID") == source]
    initial = {
        a.get("ability")
        for c in combatants
        if c.get("sourceID") == source
        for a in c.get("auras", [])
    }
    ready = tuple(
        _ready_summary(
            status, name, consumers, own_casts, own_buffs, status in initial, names, start, end
        )
        for status, name, consumers in READY
    )
    charges = 3 if 1001177 in initial else 0
    expiry = None
    guaranteed = unused = 0
    expired_charges = []
    timeline = [
        (e["timestamp"], 1, e)
        for e in own_buffs
        if e.get("abilityGameID") == 1001177
        and e.get("type") in {"applybuff", "refreshbuff", "removebuff"}
    ]
    timeline += [
        (e["timestamp"], 0, e)
        for e in own_casts
        if _event_name(e, names) in {"Fell Cleave", "Decimate"}
    ]
    for time, _, event in sorted(timeline, key=lambda row: row[:2]):
        if charges and expiry is not None and time > expiry:
            unused += charges
            expired_charges.append(((expiry - start) / 1000, charges))
            charges = 0
        if event["type"] in {"applybuff", "refreshbuff"}:
            charges = 3
            duration = event.get("duration")
            expiry = time + duration if isinstance(duration, (int, float)) else None
        elif event["type"] == "cast" and charges:
            guaranteed += 1
            charges -= 1
        elif event["type"] == "removebuff":
            if expiry is not None and time >= expiry - 100:
                unused += charges
                if charges:
                    expired_charges.append(((time - start) / 1000, charges))
            charges = 0
    if charges and expiry is not None and expiry < end:
        unused += charges
        expired_charges.append(((expiry - start) / 1000, charges))
    gcds = [
        e
        for e in own_casts
        if "weaponskill" in str(actions.get(_event_name(e, names), {}).get("type", "")).casefold()
    ]
    tomahawks = []
    index = 0
    while index < len(gcds):
        cast = gcds[index]
        if _event_name(cast, names) != "Tomahawk":
            index += 1
            continue
        last = index
        while last + 1 < len(gcds) and _event_name(gcds[last + 1], names) == "Tomahawk":
            last += 1
        previous = gcds[index - 1] if index else None
        following = gcds[last + 1] if last + 1 < len(gcds) else None
        tomahawks.append(
            WarTomahawk(
                (cast["timestamp"] - start) / 1000,
                _event_name(previous, names) if previous else None,
                (cast["timestamp"] - previous["timestamp"]) / 1000 if previous else None,
                _event_name(following, names) if following else None,
                (following["timestamp"] - gcds[last]["timestamp"]) / 1000 if following else None,
                tuple(
                    (gcds[i + 1]["timestamp"] - gcds[i]["timestamp"]) / 1000
                    for i in range(index, last)
                ),
            )
        )
        index = last + 1
    setup = _tempest_setup_windows(
        own_casts, own_buffs, names, actions, initial, start, end, targetable_time, windows
    )
    tempest_intervals = sorted(windows.get(1002677, ()))
    application_gaps = [
        (previous_end, next_begin)
        for (_, previous_end, _), (next_begin, _, _) in pairwise(tempest_intervals)
        if 0 <= next_begin - previous_end <= 1000
    ]
    avoidable = [
        (time, name, value)
        for time, name, value, factor in hit_rows
        if factor == 1
        and name != "Damnation"
        and not (any(begin <= time <= finish for begin, finish in setup + application_gaps))
    ]
    missing = tuple(sorted({((time - start) / 1000, name) for time, name, _ in avoidable}))
    observed = sum(b - a for a, b in targetable_time.intervals)
    covered = sum(
        max(0, min(b, d) - max(a, c))
        for a, b in targetable_time.intervals
        for c, d, _ in windows.get(1002677, ())
    )
    uptime = covered / observed if observed else None
    targetable_seconds = observed / 1000 if observed else None
    return WarSummary(
        uptime,
        targetable_seconds,
        sum(factor > 1 for _, _, _, factor in hit_rows),
        len(hit_rows),
        missing,
        sum(value * 0.1 for _, _, value in avoidable),
        sum(_event_name(e, names) == "Inner Release" for e in own_casts) + int(1001177 in initial),
        guaranteed,
        unused,
        ready,
        sum(_event_name(e, names) == "Infuriate" for e in own_casts),
        tuple(tomahawks),
        tuple(expired_charges),
    )
