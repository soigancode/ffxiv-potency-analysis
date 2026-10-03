"""Observed cooldown availability, with conservative unknown opening charges."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CooldownTiming:
    name: str
    ready_seconds: float | None
    longest_delay_seconds: float | None
    minimum: bool = False


def cooldown_timing(
    name: str,
    casts: tuple[float, ...],
    recast_ms: float,
    charges: int,
    start: float,
    end: float,
    windows: tuple[tuple[float, float], ...],
) -> CooldownTiming:
    """Measure readiness after the first use, intersecting eligible windows.

    Recharge continues through downtime. At a charge cap it stops. Unknown
    opening charges are modelled as empty immediately after the first use;
    an earlier observed use reanchors recharge conservatively. This bounds
    full-charge time from below without inventing an opening charge state.
    """
    times = sorted(t for t in casts if t < end)
    if not times:
        return CooldownTiming(name, None, None, charges > 1)
    available = 0
    recharge = times[0] + recast_ms
    ready_since: float | None = None
    delays = []

    def record(a: float, b: float) -> None:
        # A single wait can span several targetable windows.
        delays.append(sum(max(0.0, min(b, y, end) - max(a, x, start))
                          for x, y in windows) / 1000)

    for time in (*times[1:], end):
        while available < charges and recharge <= time:
            available += 1
            if available == charges:
                ready_since = recharge
            else:
                recharge += recast_ms
        if ready_since is not None:
            record(ready_since, time)
            ready_since = None
        if time == end:
            break
        if available == charges:
            recharge = time + recast_ms
        elif available == 0:
            # The observed use proves an unmodelled opening charge or earlier
            # recharge. Its next charge must restore within one full recast.
            recharge = time + recast_ms
        available = max(0, available - 1)
    return CooldownTiming(name, sum(delays), max(delays, default=0.0), charges > 1)


def living_windows(
    windows: tuple[tuple[float, float], ...],
    life: list[dict],
    source: int,
    start: float,
    end: float,
) -> tuple[tuple[float, float], ...]:
    """Remove recorded death-to-resurrection periods from eligible windows."""
    deaths = []
    died: float | None = None
    for event in sorted(life, key=lambda e: e.get("timestamp", 0)):
        if event.get("targetID") != source:
            continue
        if event.get("type") == "death" and died is None:
            died = max(start, event["timestamp"])
        elif event.get("type") == "resurrect" and died is not None:
            deaths.append((died, min(end, event["timestamp"])))
            died = None
    if died is not None:
        deaths.append((died, end))
    eligible = []
    for a, b in windows:
        a, b = max(a, start), min(b, end)
        for d, r in deaths:
            if r <= a or d >= b:
                continue
            if d > a:
                eligible.append((a, d))
            a = max(a, r)
        if b > a:
            eligible.append((a, b))
    return tuple(eligible)
