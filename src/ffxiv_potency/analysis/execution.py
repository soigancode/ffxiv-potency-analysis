"""Log-supported execution diagnostics, independent of report formatting."""

import re
from collections import Counter
from dataclasses import dataclass
from math import ceil

from .brd.dots import DOT_DURATION_MS, reconstruct_brd_dots
from .events import _event_name
from .targetability import TargetableTime


@dataclass(frozen=True, slots=True)
class CooldownUse:
    name: str
    uses: int
    possible: int | None
    basis: str = "full duration"


@dataclass(frozen=True, slots=True)
class Coverage:
    name: str
    covered_seconds: float
    targetable_seconds: float
    gaps: tuple[tuple[float, float], ...]
    applications: int = 0
    refreshes: int = 0
    first_application_seconds: float | None = None

    @property
    def avoidable_gaps(self) -> tuple[tuple[float, float], ...]:
        return tuple(
            (a, b)
            for a, b in self.gaps
            if self.first_application_seconds is None or b > self.first_application_seconds
        )


@dataclass(frozen=True, slots=True)
class ReadyWindow:
    start_seconds: float
    uses: int
    charges: int
    end_reason: str


@dataclass(frozen=True, slots=True)
class ReadyUse:
    name: str
    grants: int
    uses: int
    expired: int
    overwritten: int
    death_lost: int
    remaining: int
    losses: tuple[tuple[float, str], ...] = ()
    observed_uses: int = 0
    evidence_available: bool = True
    windows: tuple[ReadyWindow, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    job: str
    cooldowns: tuple[CooldownUse, ...]
    coverage: tuple[Coverage, ...]
    ready: tuple[ReadyUse, ...]
    deaths: tuple[tuple[float, float | None], ...]
    repertoire_losses: tuple[float, ...] = ()
    cast_counts: tuple[tuple[str, int], ...] = ()


def charge_maximum(
    start: float,
    end: float,
    cooldown: float,
    charges: int,
    reductions: list[tuple[float, float]],
    windows: tuple[tuple[float, float], ...],
) -> int:
    """Greedily spend while damageable, replaying recorded recast reductions.

    All times are milliseconds. Each returned charge restores one charge's
    recharge period. Reduction progress is clamped at the charge cap.
    """
    available = charges
    remaining = 0.0
    time = start
    uses = 0
    reductions = sorted((t, r) for t, r in reductions if start <= t < end)
    index = 0
    boundaries = sorted({start, end, *(t for pair in windows for t in pair)})
    while time < end:
        while index < len(reductions) and reductions[index][0] <= time:
            if available < charges:
                remaining -= reductions[index][1]
            index += 1
        while available < charges and remaining <= 1e-7:
            available += 1
            if available < charges:
                remaining += cooldown
            else:
                remaining = 0
        if any(a <= time < b for a, b in windows):
            uses += available
            if available == charges:
                remaining = cooldown
            available = 0
        next_boundary = next((t for t in boundaries if t > time), end)
        next_reduction = reductions[index][0] if index < len(reductions) else end
        next_recharge = time + remaining if available < charges else end
        next_time = min(end, next_boundary, next_reduction, next_recharge)
        if next_time <= time:
            raise ValueError("charge simulation failed to advance")
        if available < charges:
            remaining -= next_time - time
        time = next_time
    return uses


def coverage(name, active, targetable, start, applications=0, refreshes=0):
    merged = []
    for a, b in sorted(active):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    covered = 0.0
    gaps = []
    for a, b in targetable:
        cursor = a
        for c, d in merged:
            if d <= cursor or c >= b:
                continue
            if c > cursor:
                gaps.append(((cursor - start) / 1000, (min(c, b) - start) / 1000))
            overlap = max(0, min(b, d) - max(cursor, c))
            covered += overlap
            cursor = max(cursor, min(b, d))
        if cursor < b:
            gaps.append(((cursor - start) / 1000, (b - start) / 1000))
    return Coverage(
        name,
        covered / 1000,
        sum(b - a for a, b in targetable) / 1000,
        tuple(gaps),
        applications,
        refreshes,
        (merged[0][0] - start) / 1000 if merged else None,
    )


def ready_summary(
    name, status, consumers, casts, buffs, initial, life, source, start, end, duration, charges=1
):
    active = charges if status in initial else 0
    grants = active
    used = expired = overwritten = dead = 0
    expiry = None
    losses = []
    grant_packets = set()
    windows = []
    window_start = start if active else None
    window_uses = 0

    def close_window(reason):
        nonlocal window_start, window_uses
        if charges > 1 and window_start is not None:
            windows.append(ReadyWindow((window_start - start) / 1000, window_uses, charges, reason))
        window_start = None
        window_uses = 0

    events = sorted(
        [
            *(
                (e["timestamp"], 0, "cast", e)
                for e in casts
                if _event_name(e, name[1]) in consumers
            ),
            *((e["timestamp"], 1, e["type"], e) for e in buffs if e.get("abilityGameID") == status),
            *(
                (e["timestamp"], 2, "death", e)
                for e in life
                if e.get("targetID") == source and e.get("type") == "death"
            ),
        ],
        key=lambda row: (row[0], row[1]),
    )
    for time, _, kind, event in events:
        if expiry is not None and active and (time > expiry or (time == expiry and kind != "cast")):
            close_window("Expired")
            expired += active
            losses.append(((expiry - start) / 1000, "expired"))
            active = 0
        if kind in {"applybuff", "refreshbuff"}:
            packet = event.get("packetID")
            if packet is not None and packet in grant_packets:
                # FF Logs can refresh the same grant again at action resolution.
                if active:
                    expiry = time + event.get("duration", duration)
                continue
            if packet is not None:
                grant_packets.add(packet)
            if active:
                close_window("Overwritten")
                overwritten += active
                losses.append(((time - start) / 1000, "overwritten"))
            window_start = time
            window_uses = 0
            active = charges
            grants += charges
            expiry = time + event.get("duration", duration)
        elif kind == "cast" and active and (expiry is None or time <= expiry):
            active -= 1
            used += 1
            window_uses += 1
            if not active:
                close_window("Complete")
        elif kind == "death" and active:
            close_window("Death")
            dead += active
            losses.append(((time - start) / 1000, "death"))
            active = 0
        elif kind == "removebuff" and active:
            # A removal alone is not proof of expiry; a near consumer can resolve later.
            if any(
                abs(c["timestamp"] - time) <= 1000 and _event_name(c, name[1]) in consumers
                for c in casts
            ):
                continue
            if expiry is not None and time >= expiry - 100:
                close_window("Expired")
                expired += active
                losses.append(((time - start) / 1000, "expired"))
            elif any(
                e.get("type") == "death"
                and e.get("targetID") == source
                and abs(e["timestamp"] - time) <= 250
                for e in life
            ):
                close_window("Death")
                dead += active
                losses.append(((time - start) / 1000, "death"))
            close_window("Removal unconfirmed")
            active = 0
    if active and expiry is not None and expiry < end:
        close_window("Expired")
        expired += active
        losses.append(((expiry - start) / 1000, "expired"))
        active = 0
    close_window("Fight ended")
    observed_uses = sum(_event_name(c, name[1]) in consumers for c in casts)
    evidence = bool(grants or not observed_uses)
    return ReadyUse(
        name[0],
        grants,
        used,
        expired,
        overwritten,
        dead,
        active,
        tuple(losses),
        observed_uses,
        evidence,
        tuple(windows),
    )


def summarize_execution(
    job,
    casts,
    damage,
    buffs,
    debuffs,
    life,
    combatants,
    names,
    actions,
    actors,
    source,
    start,
    end,
    targetable: TargetableTime,
    buff_windows,
):
    own = sorted(
        (e for e in casts if e.get("sourceID") == source and not e.get("fake")),
        key=lambda e: e["timestamp"],
    )
    counts = Counter(_event_name(e, names) for e in own)
    selected = {
        "paladin": ("Fight or Flight", "Imperator", "Circle of Scorn", "Expiacion", "Intervene"),
        "warrior": ("Inner Release", "Infuriate"),
        "bard": ("Raging Strikes", "Battle Voice", "Radiant Finale"),
        "machinist": (
            "Reassemble",
            "Drill",
            "Air Anchor",
            "Chain Saw",
            "Wildfire",
            "Double Check",
            "Checkmate",
        ),
        "dancer": ("Devilment", "Flourish", "Technical Step"),
    }.get(job, ())
    cooldowns = []
    for name in selected:
        action = actions.get(name, {})
        recast = 120 if name == "Radiant Finale" else action.get("recast_seconds")
        text = " ".join(action.get("description", ()))
        match = re.search(r"Maximum Charges: (\d+)", text)
        charges = int(match[1]) if match else 1
        maximum = (
            charges + max(0, ceil((end - start) / 1000 / recast) - 1)
            if isinstance(recast, (int, float)) and recast > 0
            else None
        )
        basis = "full duration"
        if name == "Infuriate":
            maximum = None  # Enhanced Infuriate reduces its cooldown on recorded spenders.
        if name in {"Double Check", "Checkmate"}:
            basis = "recorded Blazing Shots"
            reductions = [
                (float(e["timestamp"]), 15000.0)
                for e in own
                if _event_name(e, names) == "Blazing Shot"
            ]
            maximum = (
                charge_maximum(
                    start,
                    end,
                    recast * 1000,
                    charges,
                    reductions,
                    targetable.intervals or ((start, end),),
                )
                if recast
                else None
            )
        cooldowns.append(CooldownUse(name, counts[name], maximum, basis))
    initial = {
        a.get("ability")
        for c in combatants
        if c.get("sourceID") == source
        for a in c.get("auras", ())
    }
    own_buffs = [
        e for e in buffs if e.get("targetID") == source and e.get("sourceID") in {source, None}
    ]
    coverage_rows = []
    repertoire = []
    if job == "bard":
        songs = {"The Wanderer's Minuet", "Wanderer's Minuet", "Mage's Ballad", "Army's Paeon"}
        song_casts = [e for e in own if _event_name(e, names) in songs]
        active = []
        for i, c in enumerate(song_casts):
            stop = min(
                end,
                c["timestamp"] + 45000,
                song_casts[i + 1]["timestamp"] if i + 1 < len(song_casts) else end,
            )
            removals = [
                e["timestamp"]
                for e in own_buffs
                if e.get("type") == "removebuff"
                and e.get("abilityGameID") == c.get("abilityGameID")
                and c["timestamp"] <= e["timestamp"] <= stop
            ]
            stop = min(
                [
                    stop,
                    *removals,
                    *[
                        e["timestamp"]
                        for e in life
                        if e.get("type") == "death"
                        and e.get("targetID") == source
                        and c["timestamp"] <= e["timestamp"] <= stop
                    ],
                ]
            )
            active.append((c["timestamp"], stop))
            if "Minuet" in _event_name(c, names) and stop < end:
                successful = {
                    (e.get("packetID"), e.get("abilityGameID"))
                    for e in damage
                    if e.get("sourceID") == source
                    and e.get("type") in {"damage", "calculateddamage"}
                    and e.get("amount", 0) > 0
                    and e.get("hitType") != 10
                    and e.get("packetID") is not None
                }
                emp = [
                    e
                    for e in own
                    if c["timestamp"] <= e["timestamp"] < stop
                    and _event_name(e, names) == "Empyreal Arrow"
                    and (e.get("packetID"), e.get("abilityGameID")) in successful
                ]
                pp = [
                    e
                    for e in own
                    if c["timestamp"] <= e["timestamp"] <= stop
                    and _event_name(e, names) == "Pitch Perfect"
                ]
                death_end = any(
                    e.get("type") == "death"
                    and e.get("targetID") == source
                    and abs(e["timestamp"] - stop) <= 250
                    for e in life
                )
                if (
                    emp
                    and not death_end
                    and not any(e["timestamp"] >= emp[-1]["timestamp"] for e in pp)
                ):
                    repertoire.append((stop - start) / 1000)
        if targetable.intervals:
            coverage_rows.append(coverage("Songs", active, targetable.intervals, start))
        # Periodic packet IDs confirm refreshes whose delayed direct hit falls
        # just beyond the apparent expiry. A missed/late Iron Jaws with no such
        # evidence must not restart a DoT.
        confirmed_refreshes = {
            (tick.application_packet, tick.target_id, tick.name)
            for tick in reconstruct_brd_dots(damage, names, source)
            if tick.matched and tick.application_name == "Iron Jaws"
        }
        # Per-enemy-instance coverage prevents Iron Jaws on one target refreshing another.
        for dot in ("Caustic Bite", "Stormbite"):
            active = []
            applications = refreshes = 0
            targets = {}
            for e in sorted(damage, key=lambda e: e.get("timestamp", 0)):
                if (
                    e.get("sourceID") != source
                    or e.get("type") != "damage"
                    or e.get("tick")
                    or e.get("hitType") == 10
                ):
                    continue
                action_name = _event_name(e, names)
                confirmed = (e.get("packetID"), e.get("targetID"), dot) in confirmed_refreshes
                if e.get("amount", 0) <= 0 and not (action_name == "Iron Jaws" and confirmed):
                    continue
                key = (e.get("targetID"), e.get("targetInstance", 1))
                if action_name == dot:
                    applications += 1
                    targets[key] = e["timestamp"] + DOT_DURATION_MS
                    active.append((e["timestamp"], min(end, e["timestamp"] + DOT_DURATION_MS)))
                elif action_name == "Iron Jaws" and key in targets and (
                    targets[key] > e["timestamp"] or confirmed
                ):
                    refreshes += 1
                    targets[key] = e["timestamp"] + DOT_DURATION_MS
                    active.append((e["timestamp"], min(end, e["timestamp"] + DOT_DURATION_MS)))
            # Only provide boss coverage when one target instance is involved.
            if len(targets) == 1 and targetable.intervals:
                coverage_rows.append(
                    coverage(dot, active, targetable.intervals, start, applications, refreshes)
                )
    if job == "dancer" and targetable.intervals:
        for status, label in [(1001821, "Standard Finish")]:
            coverage_rows.append(
                coverage(
                    label,
                    [(a, b) for a, b, _ in buff_windows.get(status, ())],
                    targetable.intervals,
                    start,
                )
            )
    ready = []
    rules = []
    if job == "machinist":
        rules = [
            ("Hypercharge", 1002688, {"Blazing Shot", "Auto Crossbow"}, 10000, 5),
            ("Full Metal Field", 1003865, {"Full Metal Field"}, 30000, 1),
            ("Excavator", 1003864, {"Excavator"}, 30000, 1),
        ]
    if job == "dancer":
        rules = [
            ("Starfall Dance", 1002700, {"Starfall Dance"}, 20000, 1),
            ("Last Dance", 1003867, {"Last Dance"}, 30000, 1),
            ("Tillana", 1002698, {"Tillana"}, 30000, 1),
            ("Dance of the Dawn", 1003870, {"Dance of the Dawn"}, 30000, 1),
            ("Fan Dance IV", 1002699, {"Fan Dance IV"}, 30000, 1),
        ]
    # Resolve actual status IDs by master-data names instead of depending on fallback IDs.
    status_names = {
        "Hypercharge": "Overheated",
        "Full Metal Field": "Full Metal Machinist",
        "Excavator": "Excavator Ready",
        "Starfall Dance": "Flourishing Starfall",
        "Last Dance": "Last Dance Ready",
        "Tillana": "Flourishing Finish",
        "Dance of the Dawn": "Dance of the Dawn Ready",
        "Fan Dance IV": "Fourfold Fan Dance",
    }
    for label, status, consumers, duration, charges in rules:
        status = next((id_ for id_, n in names.items() if n == status_names[label]), status)
        ready.append(
            ready_summary(
                (label, names),
                status,
                consumers,
                own,
                own_buffs,
                initial,
                life,
                source,
                start,
                end,
                duration,
                charges,
            )
        )
    deaths = []
    for e in sorted(life, key=lambda e: e.get("timestamp", 0)):
        if e.get("targetID") != source:
            continue
        if e.get("type") == "death":
            deaths.append(((e["timestamp"] - start) / 1000, None))
        elif e.get("type") == "resurrect" and deaths and deaths[-1][1] is None:
            deaths[-1] = (deaths[-1][0], (e["timestamp"] - start) / 1000)
    return ExecutionSummary(
        job,
        tuple(cooldowns),
        tuple(coverage_rows),
        tuple(ready),
        tuple(deaths),
        tuple(repertoire),
        tuple(sorted(counts.items())),
    )
