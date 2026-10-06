"""Conservative burst opportunities from grants and observed cooldown recovery."""

from dataclasses import dataclass
from functools import lru_cache
from math import ceil, floor
from statistics import median

from .events import _event_name
from .gcd_budget import GcdBudget, gcd_capacity


def recorded_impact_delays(casts, damage, names, source):
    """Median first-impact delay by action, using linked authoritative hits."""
    packets = {(e.get('packetID'), e.get('abilityGameID')): e for e in casts
               if e.get('sourceID') == source and e.get('packetID') is not None}
    first = {}
    for hit in damage or ():
        key = hit.get('packetID'), hit.get('abilityGameID')
        if (hit.get('sourceID') == source and hit.get('type') == 'damage'
                and not hit.get('tick') and hit.get('amount', 0) > 0 and key in packets):
            first[key] = min(first.get(key, hit['timestamp']), hit['timestamp'])
    delays = {}
    for key, time in first.items():
        event = packets[key]
        if time >= event['timestamp']:
            delays.setdefault(_event_name(event, names), []).append(time - event['timestamp'])
    return {name: median(values) for name, values in delays.items()}


def opening_clocks(casts, names, actions, source, begin, scope, regular_recast_ms=None):
    """Carry recorded animation and GCD recovery into a personal window."""
    previous = [e for e in casts if e.get('sourceID') == source and e.get('type') == 'cast'
        and not e.get('fake') and (e['timestamp'] < begin or e['timestamp'] == begin
                                 and _event_name(e, names) not in scope)]
    animation = max(begin, max((e['timestamp'] + 700 for e in previous), default=begin))
    gcds = [e for e in previous if actions.get(_event_name(e, names), {}).get('type', '').casefold()
            in {'spell', 'weaponskill'}]
    if not gcds:
        return animation, begin
    last = max(gcds, key=lambda e: e['timestamp'])
    data = actions.get(_event_name(last, names), {})
    recast = data.get('recast_seconds', 2.5)
    recast = min(recast, 2.5) if isinstance(recast, (int, float)) else 2.5
    recast_ms = regular_recast_ms if recast == 2.5 and regular_recast_ms is not None else recast * 1000
    cast_time = data.get('cast_seconds', 0) or 0
    cast_start = max((e['timestamp'] for e in casts if e.get('sourceID') == source
        and e.get('type') == 'begincast' and e.get('abilityGameID') == last.get('abilityGameID')
        and last['timestamp'] - cast_time * 1000 - 250 <= e['timestamp'] <= last['timestamp']),
        default=last['timestamp'])
    return animation, max(begin, cast_start + recast_ms)


@dataclass(frozen=True, slots=True)
class BurstAction:
    name: str
    casts: int
    hits: int
    expected: int | None
    notes: tuple[str, ...] = ()
    review: bool = False
    excluded_casts: int = 0

    @property
    def package_casts(self) -> int:
        return self.casts - self.excluded_casts


@dataclass(frozen=True, slots=True)
class ActionTiming:
    name: str
    cast_seconds: float
    hit_seconds: tuple[float, ...] = ()
    projected: bool = False


@dataclass(frozen=True, slots=True)
class HeldCleave:
    name: str
    cast_seconds: float
    earlier_seconds: float
    targets: int
    held_potency: float
    earlier_potency: float
    enhancement: str
    held_effects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HeldCast:
    name: str
    cast_seconds: float
    hits: int


@dataclass(frozen=True, slots=True)
class HoldAction:
    name: str
    inside_potency: float
    recorded_potency: float
    proposed_potency: float
    cast_seconds: float
    targets: int
    enhancement: str


@dataclass(frozen=True, slots=True)
class HoldComparison:
    actions: tuple[HoldAction, ...]
    inside_potency: float
    recorded_potency: float
    proposed_potency: float


@dataclass(frozen=True, slots=True)
class BurstWindow:
    start_seconds: float
    end_seconds: float
    actions: tuple[BurstAction, ...]
    landed_potency: float
    actual_package_potency: float | None = None
    best_package_potency: float | None = None
    alignment_notes: tuple[str, ...] = ()
    before_window_notes: tuple[str, ...] = ()
    after_window_notes: tuple[str, ...] = ()
    recorded_order: tuple[tuple[str, float], ...] = ()
    proposed_order: tuple[tuple[str, float], ...] = ()
    comparison_notes: tuple[str, ...] = ()
    boundary_events: tuple[tuple[str, float], ...] = ()
    recorded_timings: tuple[ActionTiming, ...] = ()
    proposed_timings: tuple[ActionTiming, ...] = ()
    periodic_actions: tuple[str, ...] = ()
    held_cleaves: tuple[HeldCleave, ...] = ()
    held_casts: tuple[HeldCast, ...] = ()
    attributed_followups: bool = False
    inside_package_potency: float | None = None
    hold_comparison: HoldComparison | None = None
    carried_casts: tuple[HeldCast, ...] = ()


@dataclass(frozen=True, slots=True)
class PeriodicTarget:
    cast_start: float
    cast_end: float
    windows: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class GrantedAction:
    name: str
    available: float
    deadline: float
    recast_ms: float
    potency: float
    predecessor: str | None = None
    gcd: bool = True
    impact_ms: float = 0
    unlock_duration_ms: float | None = None
    unlock_delay_ms: float = 0
    potency_windows: tuple[tuple[float, float, float], ...] = ()
    choice_group: str | None = None
    cooldown_group: str | None = None
    cooldown_ms: float = 0
    potency_resource: str | None = None
    enhanced_potency: float | None = None
    enhanced_potency_windows: tuple[tuple[float, float, float], ...] = ()
    grants_resource: str | None = None
    resource_charges: int = 0
    resource_duration_ms: float = 0
    weave_offsets: tuple[tuple[str, float], ...] = ()
    tick_potency: float = 0
    dot_duration_ms: float = 0
    periodic_targets: tuple[PeriodicTarget, ...] = ()


def expected_periodic_damage(action: GrantedAction, impact: float,
                             windows: tuple[tuple[float, float], ...],
                             factor: float = 1) -> tuple[float, float]:
    """Expected potency and mean tick time, stopping at the first damageability boundary.

    Unknown server-tick phase is averaged at one tick per three seconds.
    A later targetable interval does not resume the expired comparison.
    """
    targets = (tuple(t.windows for t in action.periodic_targets
               if t.cast_start <= impact - action.impact_ms < t.cast_end)
               if action.periodic_targets else (windows,))
    potency = moment = 0.0
    for intervals in targets:
        boundary = next((b for a, b in intervals if a <= impact < b), impact)
        duration = max(0, min(action.dot_duration_ms, boundary - impact))
        value = action.tick_potency * (1 if action.periodic_targets else factor) * duration / 3000
        potency += value
        moment += value * (impact + duration / 2)
    return potency, moment / potency if potency else impact


@dataclass(frozen=True, slots=True)
class PotencyResource:
    name: str
    charges: int = 0
    expires: float = 0
    # Recorded events outside the reordered package: spend (-1), clear (0),
    # or grant (positive count, with its duration in milliseconds).
    events: tuple[tuple[float, int, float], ...] = ()
    evidence_available: bool = True


@dataclass(frozen=True, slots=True)
class PackagePlan:
    casts: tuple[tuple[str, float], ...]
    potency: float
    weaves: tuple[tuple[str, float], ...] = ()


@lru_cache(maxsize=256)
def optimize_package(
    actions: tuple[GrantedAction, ...], windows: tuple[tuple[float, float], ...],
    start: float, end: float, *, impact_windows: tuple[tuple[float, float], ...] | None = None,
    gcd_ready: float | None = None,
    resources: tuple[PotencyResource, ...] = (),
    fixed_weaves: tuple[float, ...] = (),
    gcd_budget: GcdBudget | None = None,
) -> PackagePlan:
    """Maximize landed reference potency, including earned GCD and ability follow-ups.

    Search chronological schedules, with a shared GCD clock and 700ms weaving
    spacing. Ready durations start at the chosen predecessor cast, so changing
    a parent action also changes its follow-up's availability. Personal-window
    casts can land later; impact windows describe the actual encounter bounds.
    """
    impact_windows = windows if impact_windows is None else impact_windows
    periodic_windows = impact_windows
    windows = tuple((max(start, a), min(end, b)) for a, b in windows
                    if min(end, b) > max(start, a))
    # Preserve other recorded abilities. A selected cast needs 700ms clear
    # on either side of their activation, just like other package weaves.
    for time in fixed_weaves:
        low, high = time - 700 + .001, time + 700
        windows = tuple((x, y) for a, b in windows
                        for x, y in ((a, min(b, low)), (max(a, high), b)) if y > x)
    latest_impact = end + max((a.impact_ms for a in actions), default=0)
    impact_windows = tuple((max(start, a), min(latest_impact, b))
                           for a, b in impact_windows if min(latest_impact, b) > max(start, a))
    actions = tuple(a for a in actions if min(end, a.deadline) > max(start, a.available))
    while True:
        names = {a.name for a in actions}
        retained = tuple(a for a in actions if a.predecessor is None or a.predecessor in names)
        if len(retained) == len(actions):
            break
        actions = retained
    indices = {action.name: i for i, action in enumerate(actions)}
    choice_masks = {i: sum(1 << j for j, other in enumerate(actions)
                          if j == i or action.choice_group is not None
                          and action.choice_group == other.choice_group)
                    for i, action in enumerate(actions)}
    cooldown_masks = {}
    for i, action in enumerate(actions):
        if action.cooldown_group is not None and action.cooldown_ms:
            cooldown_masks[action.cooldown_group] = cooldown_masks.get(action.cooldown_group, 0) | (1 << i)
    cooldown_masks = {group: mask for group, mask in cooldown_masks.items() if mask.bit_count() > 1}
    cooldown_slots = {group: len(actions) + i for i, group in enumerate(cooldown_masks)}
    cooldown_lengths = {group: max(a.cooldown_ms for a in actions if a.cooldown_group == group)
                        for group in cooldown_slots}
    parents = {indices[a.predecessor] for a in actions if a.predecessor is not None and a.predecessor in indices
               and (a.unlock_duration_ms is not None or a.unlock_delay_ms)}
    timed_parents = set(parents)
    weave_parents = {i for i, a in enumerate(actions) if a.weave_offsets}
    parents.update(weave_parents)
    dependencies = {indices[a.predecessor] for a in actions
                    if a.predecessor is not None and a.predecessor in indices}
    resource_indices = {r.name: i for i, r in enumerate(resources)}
    budget_actions = {a.name: a for a in actions}
    required_gcds = gcd_capacity(gcd_budget, (), budget_actions, fixed_weaves)[0] if gcd_budget else ()

    # For equal landed potency, minimize potency-weighted impact time.
    # This fills useful early weave slots without changing the potency goal.
    best = PackagePlan((), 0)
    best_impact_cost = 0.0
    seen = {}
    def choose(time: float, gcd_ready: float, mask: int,
               parent_times: tuple[float, ...], earned: float,
               casts: tuple[tuple[str, float], ...],
               resource_state: tuple[tuple[int, float, int], ...], impact_cost: float) -> None:
        nonlocal best, best_impact_cost
        capacities, budget_state = (gcd_capacity(gcd_budget, casts, budget_actions, fixed_weaves)
                                    if gcd_budget else ((), ()))
        preserves_gcds = (not gcd_budget or len(capacities) == len(required_gcds)
                         and all(a >= b for a, b in zip(capacities, required_gcds)))
        if preserves_gcds and (earned > best.potency or earned == best.potency and (
                impact_cost < best_impact_cost or impact_cost == best_impact_cost and len(casts) > len(best.casts))):
            best = PackagePlan(casts, earned)
            best_impact_cost = impact_cost
        if gcd_budget and not preserves_gcds and not any(
                not mask & (1 << i) and a.gcd and (
                    a.recast_ms < gcd_budget.recast_ms or a.impact_ms < gcd_budget.impact_ms)
                for i, a in enumerate(actions)):
            # Greedy ordinary fillers already give the maximum remaining
            # capacity. Adding equally slow GCDs or abilities cannot recover
            # a lost slot. Faster actions remain eligible to repair it.
            return
        # A recovered consumer cooldown no longer constrains any future cast.
        # Forget its timing so equivalent histories share one search state.
        updated_times = list(parent_times)
        for parent in weave_parents:
            if all(updated_times[parent] + offset + 700 <= time
                   for _, offset in actions[parent].weave_offsets) and (
                    parent not in timed_parents or not any(not mask & (1 << child)
                        and candidate.predecessor == actions[parent].name
                        and (candidate.unlock_duration_ms is not None or candidate.unlock_delay_ms)
                        for child, candidate in enumerate(actions))):
                updated_times[parent] = float('-inf')
        for group, slot in cooldown_slots.items():
            if updated_times[slot] + cooldown_lengths[group] <= time:
                updated_times[slot] = float('-inf')
        parent_times = tuple(updated_times)
        cast_windows = windows
        for parent in weave_parents:
            if parent_times[parent] == float('-inf'):
                continue
            for _, offset in actions[parent].weave_offsets:
                low = parent_times[parent] + offset - 700 + .001
                high = parent_times[parent] + offset + 700
                if high <= time:
                    continue
                cast_windows = tuple((x, y) for a, b in cast_windows
                    for x, y in ((a, min(b, low)), (max(a, high), b)) if y > x)
        # Once a terminal grant expires, only its credited potency matters.
        # Its historical bit cannot change any future scheduling decision.
        history = mask | sum(1 << i for i, a in enumerate(actions)
                             if a.deadline <= time and i not in dependencies)
        state = history, parent_times[:len(actions)], resource_state, budget_state
        clocks = time, gcd_ready, *parent_times[len(actions):]
        previous = seen.get(state, ())
        if any(all(a <= b for a, b in zip(ready, clocks))
               and (p > earned or p == earned and (
                   cost < impact_cost or cost == impact_cost and n >= len(casts)))
               for ready, p, n, cost in previous):
            return
        seen[state] = [(ready, p, n, cost) for ready, p, n, cost in previous
                       if not (all(a <= b for a, b in zip(clocks, ready)) and
                               (earned > p or earned == p and (
                                   impact_cost < cost or impact_cost == cost and len(casts) >= n)))]
        seen[state].append((clocks, earned, len(casts), impact_cost))
        remaining = [a for i, a in enumerate(actions) if not mask & (1 << i)
                     and min(end, a.deadline) > max(time, a.available)]
        def maximum(a):
            direct = max((a.potency, a.enhanced_potency or 0,
                        *(p for _, _, p in a.potency_windows),
                        *(p for _, _, p in a.enhanced_potency_windows)))
            return direct + a.tick_potency * a.dot_duration_ms / 3000 * max(
                len(a.periodic_targets), direct / a.potency if a.potency else 1)
        gcds = [a for a in remaining if a.gcd]
        slots = ceil(max(0, end - max(time, gcd_ready)) /
                     min((a.recast_ms for a in gcds), default=2500))
        upper = (sum(sorted((maximum(a) for a in gcds), reverse=True)[:slots])
                 + sum(maximum(a) for a in remaining if not a.gcd))
        # Repeated resource tokens cannot all borrow the same fleeting cleave
        # moment. Bound bonuses by the number of casts that fit that interval,
        # while allowing optimistic overlap between distinct intervals.
        bonuses = {}
        for action in remaining:
            for a, b, potency in action.potency_windows:
                low = max(time, gcd_ready if action.gcd else time, a)
                high = min(end, b)
                if high > low and potency > action.potency:
                    bonuses.setdefault((low, high, action.gcd), []).append(
                        (potency - action.potency, action.recast_ms))
        bonus_bound = 0
        for (low, high, gcd), choices in bonuses.items():
            capacity = ceil((high - low) / min(recast for _, recast in choices)) if gcd else ceil((high - low) / 700)
            bonus_bound += sum(sorted((potency for potency, _ in choices), reverse=True)[:capacity])
        if not resources:
            upper = min(upper, sum(sorted((a.potency for a in gcds), reverse=True)[:slots])
                        + sum(a.potency for a in remaining if not a.gcd) + bonus_bound
                        + sum(a.tick_potency * a.dot_duration_ms / 3000 * max(len(a.periodic_targets), (
                            max((a.potency, *(p for _, _, p in a.potency_windows))) / a.potency
                            if a.potency else 1)) for a in remaining))
        earliest_impact = min((max(time, a.available, gcd_ready if a.gcd else time)
                               + a.impact_ms - start for a in remaining), default=0)

        def cannot_improve():
            if earned + upper < best.potency:
                return True
            if earned + upper == best.potency:
                # Every remaining hit lands at or after this optimistic bound.
                cost_bound = impact_cost + (best.potency - earned) * max(0, earliest_impact)
                return cost_bound > best_impact_cost or (cost_bound == best_impact_cost
                    and len(casts) + len(remaining) <= len(best.casts))
            return False

        if cannot_improve():
            return
        # Find a strong feasible package early so the potency upper bound can
        # prune weaker schedules without changing the exact search result.
        for i in sorted(range(len(actions)), key=lambda i: (-maximum(actions[i]), actions[i].deadline)):
            action = actions[i]
            if mask & (1 << i):
                continue
            available, deadline = action.available, min(end, action.deadline)
            if action.predecessor:
                parent = indices.get(action.predecessor)
                if parent is None or not mask & (1 << parent):
                    continue
                parent_time = parent_times[parent] if parent in parents else -1
                available = max(available, parent_time + action.unlock_delay_ms)
                if action.unlock_duration_ms is not None:
                    deadline = min(deadline, parent_time + action.unlock_duration_ms)
            earliest = max(time, available, gcd_ready if action.gcd else time)
            group = action.cooldown_group
            if (group is not None and group in cooldown_slots
                    and parent_times[cooldown_slots[group]] != float('-inf')):
                earliest = max(earliest, parent_times[cooldown_slots[group]] + action.cooldown_ms)
            # Consider the earliest slot in each interval, including intervals
            # with a different recorded potency modifier.
            boundaries = {earliest, *(a for a, _, _ in action.potency_windows if a >= earliest)}
            if gcd_budget and not action.gcd and not any(a.gcd for a in actions):
                # A package can omit ordinary GCDs. Consider weaving after the
                # next such slot rather than forcing an ability to clip it.
                anchor = max((t for name, t in casts if budget_actions[name].gcd),
                             default=gcd_budget.ready)
                for a, b in gcd_budget.windows:
                    base = max(a, anchor)
                    cycle = max(0, floor((earliest - base) / gcd_budget.recast_ms))
                    for offset in (700, 1400):
                        slot = base + cycle * gcd_budget.recast_ms + offset
                        if slot < earliest:
                            slot += gcd_budget.recast_ms
                        if earliest <= slot < min(end, b):
                            boundaries.add(slot)
            boundaries.update(t for resource in resources for t, count, _ in resource.events
                              if count > 0 and t >= earliest)
            for cast_begin, cast_end in cast_windows:
                boundaries.add(max(earliest, cast_begin))
            for hit_begin, hit_end in impact_windows:
                boundaries.add(max(earliest, hit_begin - action.impact_ms))
            for child in actions:
                if child.predecessor == action.name and child.unlock_duration_ms is not None:
                    for child_begin, _ in windows:
                        boundary = max(child.available, child_begin) - child.unlock_duration_ms + .001
                        if boundary >= earliest:
                            boundaries.add(boundary)
            for boundary in sorted(boundaries):
                slot = next_slot(boundary, cast_windows, deadline)
                if slot is None or not any(a <= slot + action.impact_ms < b
                                           for a, b in impact_windows):
                    continue
                updated = list(parent_times)
                for parent in parents:
                    if choice_masks[i] & (1 << parent):
                        updated[parent] = slot
                updated_mask = mask | choice_masks[i]
                if group is not None and group in cooldown_slots:
                    updated[cooldown_slots[group]] = (slot if cooldown_masks[group] & ~updated_mask else float('-inf'))
                for parent in parents:
                    if parent not in weave_parents and not any(not updated_mask & (1 << child) and
                               candidate.predecessor == actions[parent].name and
                               (candidate.unlock_duration_ms is not None or candidate.unlock_delay_ms)
                               for child, candidate in enumerate(actions)):
                        updated[parent] = -1.0
                potency = next((p for a, b, p in action.potency_windows if a <= slot < b),
                               action.potency)
                resource_updates = []
                for resource, (count, expiry, cursor) in zip(resources, resource_state):
                    while cursor < len(resource.events) and resource.events[cursor][0] <= slot:
                        event_time, event_count, duration = resource.events[cursor]
                        if event_time >= expiry:
                            count = 0
                        count = max(0, count - 1) if event_count < 0 else event_count
                        if event_count > 0:
                            expiry = event_time + duration
                        cursor += 1
                    if slot >= expiry:
                        count = 0
                    resource_updates.append((count, expiry, cursor))
                if action.grants_resource is not None and action.grants_resource in resource_indices:
                    index = resource_indices[action.grants_resource]
                    resource_updates[index] = (action.resource_charges,
                        slot + action.resource_duration_ms, resource_updates[index][2])
                if action.potency_resource is not None and action.potency_resource in resource_indices:
                    index = resource_indices[action.potency_resource]
                    count, expiry, cursor = resource_updates[index]
                    if count:
                        potency = next((p for a, b, p in action.enhanced_potency_windows
                                        if a <= slot < b), action.enhanced_potency
                                       if action.enhanced_potency is not None else potency)
                        resource_updates[index] = count - 1, expiry, cursor
                impact = slot + action.impact_ms
                periodic, mean_tick = expected_periodic_damage(action, impact, periodic_windows,
                    potency / action.potency if action.potency else 1)
                choose(slot + 700, slot + action.recast_ms if action.gcd else gcd_ready,
                       updated_mask, tuple(updated), earned + potency + periodic, (*casts, (action.name, slot)),
                       tuple(resource_updates), impact_cost + potency * (impact - start)
                       + periodic * (mean_tick - start))
                if cannot_improve():
                    return

    choose(start, max(start, gcd_ready if gcd_ready is not None else start),
           0, (*(float('-inf') if i in weave_parents else -1.0 for i, _ in enumerate(actions)),
               *(float('-inf') for _ in cooldown_slots)), 0, (),
           tuple((r.charges, r.expires, 0) for r in resources), 0)
    selected = {name: time for name, time in best.casts}
    weaves = tuple((key, selected[a.name] + offset) for a in actions if a.name in selected
                   for key, offset in a.weave_offsets)
    return PackagePlan(best.casts, best.potency, tuple(sorted(weaves, key=lambda row: row[1])))


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
    return tuple(name for name, _ in optimize_package(actions, windows, start, end).casts)


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
