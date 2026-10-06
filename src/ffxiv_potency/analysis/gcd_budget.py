"""Protect ordinary landed GCD opportunities while comparing burst packages."""

from dataclasses import dataclass
from itertools import pairwise
from math import ceil
from statistics import median

from .events import _event_name


@dataclass(frozen=True, slots=True)
class GcdBudget:
    windows: tuple[tuple[float, float], ...]
    ready: float
    recast_ms: float = 2500
    impact_ms: float = 0


def recorded_gcd_budget(casts, names, actions, source, begin, finish, windows, ready, delays):
    """Infer the regular GCD rhythm, then extend protection to the next boundary."""
    regular = {name for name, data in actions.items()
               if data.get('type', '').casefold() in {'spell', 'weaponskill'}
               and data.get('recast_seconds', 2.5) == 2.5 and not data.get('cast_seconds')}
    times = sorted({e['timestamp'] for e in casts if e.get('sourceID') == source
                    and e.get('type') == 'cast' and not e.get('fake')
                    and _event_name(e, names) in regular})
    gaps = sorted(b - a for a, b in pairwise(times) if 1800 <= b - a <= 2550)
    recast = median(gaps[:max(1, len(gaps) // 2)]) if gaps else 2500
    protected = tuple((max(begin, a), b) for a, b in windows if a < finish and b > begin) if regular else ()
    impact = min((delay for name, delay in delays.items() if name in regular), default=0)
    return GcdBudget(protected, max(begin, ready), recast, impact)


def gcd_capacity(budget, casts, actions, fixed_weaves=()):
    """Fill unused slots without resources or scored potency.

    Return landed counts and a search-state signature. Only generic GCDs that
    fit before the next selected GCD are inserted. Past filler counts remain
    in the signature so histories with different clipping cannot be merged.
    """
    chosen = [(actions[name], time) for name, time in casts]
    abilities = [time for action, time in chosen if not action.gcd]
    abilities += [time + offset for action, time in chosen for _, offset in action.weave_offsets]
    abilities = sorted(set(abilities + list(fixed_weaves)))
    counts = []
    signatures = []
    ready = budget.ready
    for begin, end in budget.windows:
        intervals = [(begin, end)]
        for time in abilities:
            low, high = time - 700 + .001, time + 700
            intervals = [(x, y) for a, b in intervals for x, y in
                         ((a, min(b, low)), (max(a, high), b)) if y > x]
        ready = max(begin, ready)
        count = 0

        def fill(deadline, intervals=intervals, end=end):
            nonlocal ready, count
            for a, b in intervals:
                slot = max(ready, a)
                limit = min(b, deadline, end - budget.impact_ms)
                if slot >= limit:
                    continue
                amount = ceil((limit - slot) / budget.recast_ms)
                count += amount
                ready = slot + amount * budget.recast_ms

        gcds = sorted(((action, time) for action, time in chosen
                       if action.gcd and begin <= time < end), key=lambda row: row[1])
        committed = 0
        last = begin
        for action, time in gcds:
            fill(min(time - budget.recast_ms + .001, end - budget.impact_ms))
            if time < ready - .001:
                return (), ()
            count += int(time + action.impact_ms < end)
            ready = time + action.recast_ms
            committed, last = count, time
        signatures.append((committed, tuple(t for t in abilities if last <= t < end)))
        fill(end - budget.impact_ms)
        counts.append(count)
    return tuple(counts), tuple(signatures)
