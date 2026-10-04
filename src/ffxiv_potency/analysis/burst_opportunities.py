"""Conservative burst opportunities from grants and observed cooldown recovery."""

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class BurstAction:
    name: str
    casts: int
    hits: int
    expected: int | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BurstWindow:
    start_seconds: float
    end_seconds: float
    actions: tuple[BurstAction, ...]
    landed_potency: float


@dataclass(frozen=True, slots=True)
class GrantedAction:
    name: str
    available: float
    deadline: float
    recast_ms: float
    potency: float
    predecessor: str | None = None


def next_slot(time: float, windows: tuple[tuple[float, float], ...], end: float) -> float | None:
    return next((max(time, a) for a, b in windows if max(time, a) < min(b, end)), None)


def granted_package(
    actions: tuple[GrantedAction, ...], windows: tuple[tuple[float, float], ...],
    start: float, end: float,
) -> tuple[str, ...]:
    """Fit granted GCDs by reference potency, respecting combo order and expiry.

    This is a package bound, not a replacement rotation. Reference recasts are
    conservative without assuming an unrecorded skill-speed or haste benefit.
    Downtime does not stop the GCD clock, but actions need an eligible target.
    """
    indices = {a.name: i for i, a in enumerate(actions)}

    @lru_cache(None)
    def choose(time: float, mask: int) -> tuple[float, tuple[str, ...]]:
        best: tuple[float, tuple[str, ...]] = (0.0, ())
        for i, action in enumerate(actions):
            if mask & (1 << i):
                continue
            predecessor = indices.get(action.predecessor) if action.predecessor else None
            if action.predecessor and (predecessor is None or not mask & (1 << predecessor)):
                continue
            slot = next_slot(max(time, action.available), windows, min(end, action.deadline))
            if slot is None:
                continue
            value, names = choose(slot + action.recast_ms, mask | (1 << i))
            candidate = (action.potency + value, (action.name, *names))
            if candidate[0] > best[0] or candidate[0] == best[0] and len(candidate[1]) > len(best[1]):
                best = candidate
        return best

    return choose(start, 0)[1]


def cooldown_opportunities(
    casts: tuple[float, ...], recast_ms: float, charges: int,
    start: float, end: float, windows: tuple[tuple[float, float], ...],
) -> int | None:
    """Count additional ready uses without preventing any later recorded use.

    Opening charges are unknown. After the first use, assume no spare charges.
    An observed early use reanchors that lower bound, as in cooldown timing.
    The comparison keeps every recorded use fixed. It therefore does not
    accuse routine outside-window uses or hypothesize a different rotation.
    """
    times = tuple(sorted(casts))
    actual = sum(start <= t < end for t in times)
    if not times or times[0] >= start:
        return actual if actual and (charges == 1 or actual >= charges) else None

    def replay(extra: tuple[float, ...], cutoff: float) -> tuple[int, float, frozenset[float]]:
        available = 0
        recharge = times[0] + recast_ms
        deficits = set()
        events = sorted([(t, False) for t in times[1:] if t <= cutoff]
                        + [(t, True) for t in extra if t <= cutoff])
        for time, hypothetical in events:
            while available < charges and recharge <= time:
                available += 1
                recharge = recharge + recast_ms if available < charges else float("inf")
            if available == 0:
                if hypothetical:
                    return available, recharge, frozenset({float("inf")})
                deficits.add(time)
                recharge = time + recast_ms
            else:
                if available == charges:
                    recharge = time + recast_ms
                available -= 1
        while available < charges and recharge <= cutoff:
            available += 1
            recharge = recharge + recast_ms if available < charges else float("inf")
        return available, recharge, frozenset(deficits)

    extra: tuple[float, ...] = ()
    time = start
    baseline = replay((), times[-1])[2]
    # Any added use must fit a targetable, living interval and a weaving slot.
    while time < end:
        available, recharge, _ = replay(extra, time)
        candidate = next_slot(time if available else max(time, recharge), windows, end)
        if candidate is None:
            break
        if any(abs(candidate - t) < 700 for t in (*times, *extra)):
            time = candidate + 700
            continue
        proposed = (*extra, candidate)
        if replay(proposed, max(times[-1], end))[2] <= baseline:
            extra = proposed
        time = candidate + 700
    return actual + len(extra)
