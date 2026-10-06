"""Build feasible packages from job rules and recorded resource evidence."""

import re
from collections import Counter
from dataclasses import dataclass, replace
from itertools import pairwise

from .burst_opportunities import (
    ActionTiming,
    BurstAction,
    BurstWindow,
    GrantedAction,
    PeriodicTarget,
    cooldown_opportunities,
    expected_periodic_damage,
    opening_clocks,
    optimize_package,
    recorded_impact_delays,
)
from .cooldown_timing import living_windows
from .damage import landed_fraction
from .events import _event_name
from .gcd_budget import recorded_gcd_budget
from .weaving import attach_weaves


@dataclass(frozen=True, slots=True)
class PackageRules:
    cooldowns: tuple[str, ...]
    ready: tuple[tuple[str, tuple[str, ...], int], ...]
    chains: tuple[tuple[str, ...], ...] = ()
    witnessed: tuple[str, ...] = ()
    status_ids: tuple[tuple[str, int], ...] = ()
    multipliers: tuple[tuple[str, str, float], ...] = ()
    earned: tuple[tuple[str, str, int], ...] = ()
    periodic: tuple[str, ...] = ()


def reference_potency(name, actions):
    spec = actions.get(name, {}).get('potency') or {}
    return spec.get('base', 0)


def annotate_package_orders(windows, casts, names, actions, actors, source, start,
                            targetability, overkills, phase_locks, damage=()):
    """Include extra weaves and attach authoritative hit evidence."""
    own = sorted((e for e in casts if e.get('sourceID') == source
                  and e.get('type') == 'cast' and not e.get('fake')),
                 key=lambda e: e['timestamp'])
    own = list({(e.get('packetID', e['timestamp']), e.get('abilityGameID')): e
                for e in own}.values())
    output = []
    packet_hits = {}
    for hit in damage:
        if (hit.get('sourceID') == source and hit.get('type') == 'damage'
                and not hit.get('tick') and hit.get('amount', 0) > 0
                and hit.get('packetID') is not None):
            packet_hits.setdefault((hit.get('packetID'), hit.get('abilityGameID')), set()).add(
                (hit['timestamp'] - start) / 1000)
    for window in windows:
        begin = start + window.start_seconds * 1000
        finish = start + window.end_seconds * 1000
        within = [e for e in own if begin <= e['timestamp'] < finish]
        order = list(window.recorded_order)
        proposed = list(window.proposed_order)
        proposed_counts = Counter(name for name, _ in proposed)
        extra_counts = Counter()
        timings = {}
        proposed_timings = {(t.name, t.cast_seconds): t for t in window.proposed_timings}
        for event in within:
            name = _event_name(event, names)
            entry = name, (event['timestamp'] - start) / 1000
            if actions.get(name, {}).get('potency'):
                timings[entry] = ActionTiming(name, entry[1], tuple(sorted(packet_hits.get(
                    (event.get('packetID'), event.get('abilityGameID')), ()))))
            if actions.get(name, {}).get('type', '').casefold() == 'ability':
                extra_weave = entry not in order or not actions.get(name, {}).get('potency')
                if entry not in order:
                    order.append(entry)
                if extra_weave:
                    extra_counts[name] += 1
                if proposed and extra_weave and extra_counts[name] > proposed_counts[name]:
                    proposed.append(entry)
                    if entry in timings:
                        proposed_timings[entry] = timings[entry]
        for entry in proposed:
            if entry not in proposed_timings and entry in timings:
                proposed_timings[entry] = timings[entry]
        targets = {e.get('targetID') for e in within}
        boundaries = set()
        for target in targets:
            actor = actors.get(target, {})
            if actor.get('type') != 'NPC':
                continue
            for low, high in phase_locks.get(target, ()):
                # Use the same lethal-hit threshold as the package scheduler,
                # rather than the earlier allowance used for ghost attribution.
                hits = [e['timestamp'] for e in overkills if e.get('targetID') == target
                        and e.get('overkill', 0) > 0 and low <= e['timestamp'] <= high]
                if hits:
                    time = min(min(hits), low + 2500)
                    if begin <= time <= finish:
                        boundaries.add((f"HP lock reached: {actor.get('name', target)}",
                                        (time - start) / 1000))
            for event in targetability:
                if (event.get('sourceID') == target and event.get('targetable') == 0
                        and begin <= event['timestamp'] <= finish):
                    boundaries.add((f"Untargetable: {actor.get('name', target)}",
                                    (event['timestamp'] - start) / 1000))
        output.append(replace(window, recorded_order=tuple(sorted(order, key=lambda row: row[1])),
            proposed_order=tuple(sorted(proposed, key=lambda row: row[1])),
            recorded_timings=tuple(timings[entry] for entry in order if entry in timings),
            proposed_timings=tuple(proposed_timings[entry] for entry in proposed if entry in proposed_timings),
            boundary_events=tuple(sorted(boundaries, key=lambda row: row[1]))))
    return tuple(output)


def exclude_trailing_hp_lock_casts(windows, casts, damage, names, source, start, endings):
    """Keep the first HP-lock ghost per target, preserving raw cast evidence."""
    locked = {(round(start + seconds * 1000), name)
              for name, entries in endings for seconds, reason in entries
              if reason == 'phase HP lock'}
    if not locked:
        return windows
    landed = {(e.get('packetID'), e.get('abilityGameID')) for e in damage
              if e.get('sourceID') == source and e.get('type') == 'damage'
              and not e.get('tick') and e.get('amount', 0) > 0}
    own = sorted((e for e in casts if e.get('sourceID') == source
                  and e.get('type') == 'cast' and not e.get('fake')),
                 key=lambda e: e['timestamp'])
    output = []
    for window in windows:
        seen = set()
        packets = set()
        excluded = Counter()
        excluded_order = set()
        scope = {a.name for a in window.actions}
        for event in own:
            time = event['timestamp']
            if not window.start_seconds <= (time - start) / 1000 < window.end_seconds:
                continue
            name = _event_name(event, names)
            key = event.get('packetID', time), event.get('abilityGameID')
            if key in packets:
                continue
            packets.add(key)
            target = event.get('targetID'), event.get('targetInstance', 1)
            if key in landed:
                seen.discard(target)
            elif name in scope and (round(time), name) in locked:
                if target in seen:
                    excluded[name] += 1
                    excluded_order.add((name, (time - start) / 1000))
                seen.add(target)
        actions = []
        for action in window.actions:
            count = excluded[action.name]
            if not count:
                actions.append(action)
                continue
            expected = action.expected
            if (window.actual_package_potency is not None
                    and window.actual_package_potency == window.best_package_potency
                    and expected is not None and expected == action.casts):
                expected -= count
            actions.append(replace(action, excluded_casts=count, expected=expected))
        proposed_order = window.proposed_order
        if proposed_order == window.recorded_order:
            proposed_order = tuple(entry for entry in proposed_order if entry not in excluded_order)
        output.append(replace(window, actions=tuple(actions), proposed_order=proposed_order))
    return tuple(output)


def summarize_packages(casts, damage, buffs, life, names, actions, source, start, end,
                       windows, targetable, rules, *, values=None, enhancements=None, packet_values=None, uncertain_values=(), primary_hits=None,
                       resource_model=None, periodic_target_windows=None, fixed_casts=()):
    """Optimize known resources jointly. Gauge spends prove availability at their cast.

    Cooldown candidates retain later recorded uses. Missing opening charges
    remain unknown. Target windows apply to impacts as well as casts, including
    observed phase locks. Selected DoTs include expected ticks until the first
    damageability boundary, using the same estimate for recorded and proposed casts.
    """
    values = {} if values is None else values
    enhancements = {} if enhancements is None else enhancements
    packet_values = {} if packet_values is None else packet_values
    primary_hits = {} if primary_hits is None else primary_hits
    periodic_target_windows = {} if periodic_target_windows is None else periodic_target_windows
    own = sorted((e for e in casts if e.get('sourceID') == source
                  and e.get('type') == 'cast' and not e.get('fake')),
                 key=lambda e: e['timestamp'])
    own = list({(e.get('packetID', e['timestamp']), e.get('abilityGameID')): e
                for e in own}.values())
    scope = tuple(dict.fromkeys((*rules.cooldowns,
        *(name for _, consumers, _ in rules.ready for name in consumers),
        *(name for chain in rules.chains for name in chain), *rules.witnessed)))
    delays = recorded_impact_delays(own, damage, names, source)
    packets = {}
    for hit in damage or ():
        if (hit.get('sourceID') == source and hit.get('type') == 'damage'
                and not hit.get('tick') and hit.get('amount', 0) > 0):
            packets.setdefault((hit.get('packetID'), hit.get('abilityGameID')), []).append(hit)
    target_windows = targetable.intervals if targetable is not None else ()
    known = bool(target_windows)
    living = living_windows(target_windows, life, source, start, end) if known else ()
    rows = []
    for begin, finish in windows:
        within = [e for e in own if begin <= e['timestamp'] < finish
                  and (e.get('packetID'), e.get('abilityGameID')) not in fixed_casts]
        actual = Counter(_event_name(e, names) for e in within)
        hits = Counter()
        actual_potency = 0.0
        for event in within:
            name = _event_name(event, names)
            if name not in scope:
                continue
            landed = packets.get((event.get('packetID'), event.get('abilityGameID')), ())
            hits[name] += len(landed)
            spec = actions.get(name, {}).get('potency') or {}
            value = packet_values.get((event.get('packetID'), event.get('abilityGameID')),
                next((p for a, b, p in enhancements.get(name, ()) if a <= event['timestamp'] < b),
                     values.get(name, reference_potency(name, actions))))
            primary = primary_hits.get((event.get('packetID'), event.get('abilityGameID')),
                                       landed[0] if landed else None)
            actual_potency += sum(value * (1 if hit is primary else
                spec.get('falloff', {}).get('additional_target_multiplier', 1)) * landed_fraction(hit)
                for hit in landed)
            if name in rules.periodic and targetable is not None:
                dot = spec.get('damage_over_time', {})
                periodic = GrantedAction(name, 0, 0, 0, value,
                    tick_potency=dot.get('potency_per_tick', 0),
                    dot_duration_ms=dot.get('duration_seconds', 0) * 1000)
                actual_potency += sum(expected_periodic_damage(periodic, hit['timestamp'],
                    periodic_target_windows.get((hit.get('targetID'), hit.get('targetInstance', 1)),
                                                targetable.intervals), landed_fraction(hit))[0] for hit in landed)
        window_values = {n: values.get(n, reference_potency(n, actions)) for n in scope}
        potency_windows = {}
        for n in scope:
            spec = actions.get(n, {}).get('potency') or {}
            cleaves = []
            for e in within:
                if _event_name(e, names) != n or n == 'Refulgent Arrow':
                    continue
                recorded = packets.get((e.get('packetID'), e.get('abilityGameID')), ())
                targets = {(hit.get('targetID'), hit.get('targetInstance', 1)) for hit in recorded}
                if len(targets) > 1:
                    primary = primary_hits.get((e.get('packetID'), e.get('abilityGameID')), recorded[0])
                    factor = sum((1 if hit is primary else
                        spec.get('falloff', {}).get('additional_target_multiplier', 1)) * landed_fraction(hit)
                        for hit in recorded)
                    cleaves.append((e['timestamp'], e['timestamp'] + .001, factor))
            planned_enhancements = () if resource_model is not None else enhancements.get(n, ())
            boundaries = sorted({begin, finish,
                *(max(begin, min(finish, t)) for a, b, _ in planned_enhancements for t in (a, b)),
                *(t for a, b, _ in cleaves for t in (a, b))})
            segments = []
            for a, b in pairwise(boundaries):
                value = next((p for x, y, p in planned_enhancements if x <= a < y), window_values[n])
                factor = next((p for x, y, p in cleaves if x <= a < y), 1)
                if value * factor != window_values[n]:
                    segments.append((a, b, value * factor))
            potency_windows[n] = tuple(segments)
        candidates = []
        labels = {}
        by_name = {}
        unknown = set(uncertain_values)

        def add(name, available, deadline, predecessor=None, duration=None, ordinal=0,
                window_values=window_values, unknown=unknown, candidates=candidates,
                labels=labels, by_name=by_name, potency_windows=potency_windows, begin=begin,
                finish=finish, within=within):
            data = actions.get(name, {})
            if duration is not None and duration >= deadline - available:
                duration = None
            value = window_values.get(name, reference_potency(name, actions))
            if not value and data.get('potency'):
                unknown.add(name)
            gcd = data.get('type', '').casefold() in {'spell', 'weaponskill'}
            recast = data.get('recast_seconds', 2.5)
            gcd_recast = min(recast, 2.5) * 1000 if gcd else 0
            charge_match = re.search(r'Maximum Charges: (\d+)', ' '.join(data.get('description', ())))
            charged = charge_match is not None and int(charge_match[1]) > 1
            if not gcd and not charged:
                previous = max((e['timestamp'] for e in own if e['timestamp'] < begin
                    and _event_name(e, names) == name), default=None)
                if previous is not None:
                    available = max(available, previous + data.get('recast_seconds', 0) * 1000)
            key = f'{name}:{len(candidates)}'
            candidate = GrantedAction(key, available, deadline, gcd_recast, value,
                predecessor, gcd=gcd, impact_ms=delays.get(name, 0),
                unlock_duration_ms=duration, potency_windows=potency_windows.get(name, ()),
                cooldown_group=name if not gcd and not charged else None,
                cooldown_ms=data.get('recast_seconds', 0) * 1000 if not gcd else 0)
            if name in rules.periodic:
                dot = (data.get('potency') or {}).get('damage_over_time', {})
                applications = [e for e in within if _event_name(e, names) == name]
                primary_target = next(((e.get('targetID'), e.get('targetInstance', 1))
                    for e in applications if (e.get('targetID'), e.get('targetInstance', 1))
                    in periodic_target_windows), None)
                targets = []
                if primary_target is not None:
                    targets.append(PeriodicTarget(begin, finish, periodic_target_windows[primary_target]))
                    for e in applications:
                        other_targets = {(h.get('targetID'), h.get('targetInstance', 1))
                            for h in packets.get((e.get('packetID'), e.get('abilityGameID')), ())}
                        targets.extend(PeriodicTarget(e['timestamp'], e['timestamp'] + .001,
                            periodic_target_windows[target]) for target in other_targets
                            if target != primary_target and target in periodic_target_windows)
                candidate = replace(candidate, tick_potency=dot.get('potency_per_tick', 0),
                                    dot_duration_ms=dot.get('duration_seconds', 0) * 1000,
                                    periodic_targets=tuple(targets))
            candidates.append(candidate)
            labels[key] = name
            by_name.setdefault(name, []).append(key)
            return key

        # Each CD use is a token with a proven readiness bound. Subsequent
        # tokens also depend on the selected previous use's recovery.
        for name in rules.cooldowns:
            data = actions.get(name, {})
            recast = data.get('recast_seconds')
            if not isinstance(recast, (int, float)) or recast <= 0:
                unknown.add(name)
                continue
            match = re.search(r'Maximum Charges: (\d+)', ' '.join(data.get('description', ())))
            charges = int(match[1]) if match else 1
            times = tuple(e['timestamp'] for e in own if _event_name(e, names) == name)
            count = cooldown_opportunities(times, recast * 1000, charges, begin, finish, living)
            if count is None:
                unknown.add(name)
                continue
            previous = max((t for t in times if t < begin), default=None)
            recorded = [t for t in times if begin <= t < finish]
            ready = max(begin, previous + recast * 1000) if previous is not None else (
                recorded[0] if recorded else begin)
            later = min((t for t in times if t >= finish), default=None)
            for i in range(count):
                available = min(recorded[i], ready) if i < len(recorded) else ready
                deadline = min(finish, later - recast * 1000 + 1) if later is not None and charges == 1 else finish
                if available >= deadline:
                    continue
                key = add(name, available, deadline, by_name[name][-1] if i else None)
                if i and charges == 1:
                    candidates[-1] = replace(candidates[-1], unlock_delay_ms=recast * 1000)
                ready = available + recast * 1000

        multipliers = {(status, name): factor for status, name, factor in rules.multipliers}
        for status, consumers, charges in rules.ready:
            if charges > 1:
                pattern = r'Grants (\d+) stacks of ' + re.escape(status)
                stack_count = next((match for data in actions.values() if
                    (match := re.search(pattern, ' '.join(data.get('description', ()))))), None)
                if stack_count is None:
                    unknown.update(consumers)
                    continue
                charges = int(stack_count[1])
            ids = {id_ for id_, name in names.items() if name == status}
            ids.update(id_ for label, id_ in rules.status_ids if label == status)
            grants = sorted((e for e in buffs if e.get('targetID') == source
                and e.get('sourceID') in {source, None} and e.get('abilityGameID') in ids
                and e.get('type') in {'applybuff', 'refreshbuff'} and e['timestamp'] < finish),
                key=lambda e: e['timestamp'])
            for grant in grants:
                time = grant['timestamp']
                duration = grant.get('duration')
                if not isinstance(duration, (int, float)):
                    unknown.update(consumers)
                    continue
                expiry = min(end, time + duration,
                    min((g['timestamp'] for g in grants if g['timestamp'] > time), default=end),
                    min((e['timestamp'] for e in life
                    if e.get('type') == 'death' and e.get('targetID') == source
                    and e['timestamp'] >= time), default=end))
                if any(finish <= e['timestamp'] < expiry and _event_name(e, names) in consumers
                       and len(packets.get((e.get('packetID'), e.get('abilityGameID')), ())) > 1
                       for e in own):
                    unknown.update(consumers)
                    for chain in rules.chains:
                        if chain[0] in consumers:
                            unknown.update(chain)
                    continue
                used = [e for e in own if time <= e['timestamp'] < min(begin, expiry)
                        and _event_name(e, names) in consumers]
                if time < begin and any(time <= e['timestamp'] < expiry
                    and _event_name(e, names) in consumers
                    and (e.get('packetID'), e.get('abilityGameID')) in fixed_casts for e in own):
                    continue
                if time < begin and any(e.get('type') == 'removebuff'
                    and e.get('targetID') == source and e.get('abilityGameID') in ids
                    and time < e['timestamp'] < begin for e in buffs):
                    continue
                parent = next((e for e in own if grant.get('packetID') is not None
                    and e.get('packetID') == grant.get('packetID')
                    and e.get('abilityGameID') == grant.get('extraAbilityGameID')), None)
                parent_key = None
                available = max(begin, time)
                if parent is not None:
                    parent_name = _event_name(parent, names)
                    parent_key = (next(iter(by_name.get(parent_name, ())), None)
                                  if parent['timestamp'] >= begin else None)
                    if parent_key is None and actions.get(parent_name, {}).get('type', '').casefold() in {'spell', 'weaponskill'}:
                        available = max(available, parent['timestamp'] + 2500)
                charge_parent = parent_key
                for i in range(max(0, charges - len(used))):
                    name = max(consumers, key=lambda n: window_values.get(n, reference_potency(n, actions)) * multipliers.get((status, n), 1))
                    if parent_key:
                        available = begin
                    predecessor = charge_parent
                    strongest = min((window_values[name], *(p for _, _, p in potency_windows[name]))) * multipliers.get((status, name), 1)
                    alternatives = (name, *(n for n in consumers if n != name and (
                        actions.get(n, {}).get('recast_seconds') != actions.get(name, {}).get('recast_seconds')
                        or max((window_values[n], *(p for _, _, p in potency_windows[n]))) * multipliers.get((status, n), 1) > strongest)))
                    group = f'{status}:{time}:{i}'
                    keys = []
                    for alternative in alternatives:
                        keys.append(add(alternative, available, min(finish, expiry), predecessor,
                            duration if parent_key and not i else None, i))
                        factor = multipliers.get((status, alternative), 1)
                        candidates[-1] = replace(candidates[-1], choice_group=group,
                            potency=candidates[-1].potency * factor,
                            potency_windows=tuple((a, b, p * factor)
                                                  for a, b, p in candidates[-1].potency_windows))
                    key = keys[0]
                    charge_parent = key
                    for chain in rules.chains:
                        if name == chain[0]:
                            for child in chain[1:]:
                                key = add(child, begin, min(finish, expiry), key)
            if not grants and not any(n in by_name for n in consumers):
                # A deterministic follow-up can be earned by a candidate even
                # when the player did not generate its recorded ready effect.
                parent = next((n for n in by_name if any(
                    status in line and 'Grants' in line for line in actions.get(n, {}).get('description', ()))), None)
                if parent:
                    description = ' '.join(actions[parent].get('description', ()))
                    duration = re.search(r'Grants ' + re.escape(status) + r' Duration: (\d+)s', description)
                    key = by_name[parent][0]
                    add(consumers[0], begin, finish, key,
                        int(duration[1]) * 1000 if duration else None)
                elif not any(actual[n] for n in consumers):
                    unknown.update(consumers)
        for name in rules.witnessed:
            for event in within:
                if _event_name(event, names) == name:
                    add(name, event['timestamp'], finish, by_name[name][-1] if name in by_name else None)
                    value = packet_values.get((event.get('packetID'), event.get('abilityGameID')))
                    if value is not None:
                        basis = candidates[-1].potency
                        candidates[-1] = replace(candidates[-1], potency=value,
                            potency_windows=tuple((a, b, p * value / basis)
                                                  for a, b, p in candidates[-1].potency_windows) if basis else ())
        for parent, child, count in rules.earned:
            for parent_key in by_name.get(parent, ()):
                # A recorded spend already includes its generated resource.
                # Couple that token to the selected generator rather than
                # awarding the same gauge twice.
                recorded_parent = next((e['timestamp'] for e in within if _event_name(e, names) == parent), None)
                parent_cast = recorded_parent if recorded_parent is not None else begin
                ready_reward = any(child in consumers for _, consumers, _ in rules.ready)
                children = tuple(c.name for c in candidates if labels[c.name] == child
                                 and (c.predecessor == parent_key or c.available >= parent_cast
                                      and (not ready_reward or recorded_parent is not None)))
                if children:
                    first = next((i for i, c in enumerate(candidates) if c.name == children[0]), None)
                    if first is not None:
                        candidates[first] = replace(candidates[first], predecessor=parent_key)
                else:
                    for _ in range(count):
                        add(child, begin, finish, parent_key)
        animation_ready, gcd_ready = opening_clocks(casts, names, actions, source, begin, scope)
        resources = ()
        if resource_model is not None:
            candidates, resources = resource_model(tuple(candidates), labels, begin, finish, scope)
            uncertain_resources = {r.name for r in resources if not r.evidence_available}
            unknown.update(labels[c.name] for c in candidates
                           if c.potency_resource in uncertain_resources)
        candidates, labels, fixed_weaves = attach_weaves(candidates, labels, own, names, actions,
                                                        begin, finish, fixed_casts=fixed_casts)
        budget = recorded_gcd_budget(casts, names, actions, source, begin, finish, living,
                                     begin, delays)
        animation_ready, gcd_ready = opening_clocks(
            casts, names, actions, source, begin, scope, budget.recast_ms)
        budget = replace(budget, ready=max(animation_ready, gcd_ready))
        candidates = tuple(replace(c, recast_ms=budget.recast_ms)
                           if c.gcd and c.recast_ms == 2500 else c for c in candidates)
        plan = optimize_package(tuple(candidates), living, animation_ready, finish,
            impact_windows=target_windows, gcd_ready=gcd_ready,
            resources=resources, fixed_weaves=fixed_weaves, gcd_budget=budget)
        for chain in rules.chains:
            if chain[0] in unknown:
                unknown.update(chain)
        for _ in range(len(candidates)):
            inherited = {labels[c.name] for c in candidates
                         if c.predecessor in labels and labels[c.predecessor] in unknown}
            if inherited <= unknown:
                break
            unknown.update(inherited)
        expected = Counter(labels[key] for key, _ in plan.casts)
        best = plan.potency
        recorded_order = tuple((_event_name(e, names), (e['timestamp'] - start) / 1000)
                               for e in within if _event_name(e, names) in scope)
        proposed_order = tuple((labels[key], (time - start) / 1000) for key, time in plan.casts)
        proposed_order += tuple((labels[key], (time - start) / 1000) for key, time in plan.weaves)
        proposed_order = tuple(sorted(proposed_order, key=lambda row: row[1]))
        candidate_by_key = {c.name: c for c in candidates}
        proposed_timings = tuple(ActionTiming(labels[key], (time - start) / 1000,
            ((time + candidate_by_key[key].impact_ms - start) / 1000,) if labels[key] in delays else (), True)
            for key, time in plan.casts if actions.get(labels[key], {}).get('potency'))
        proposed_timings += tuple(ActionTiming(labels[key], (time - start) / 1000,
            ((time + delays[labels[key]] - start) / 1000,) if labels[key] in delays else (), True)
            for key, time in plan.weaves if actions.get(labels[key], {}).get('potency'))
        if actual_potency >= best:
            # Keep a recorded package intact as an independently feasible lower
            # bound when uncertain resource or haste data understate the model.
            expected = actual
            best = actual_potency
            proposed_order = recorded_order
            proposed_timings = ()
        rows.append(BurstWindow((begin - start) / 1000, (finish - start) / 1000,
            tuple(BurstAction(n, actual[n], hits[n], None if not known or n in unknown else expected[n],
                ('non-damaging resource grant',) if not actions.get(n, {}).get('potency') else ()) for n in scope),
            actual_potency, actual_potency if known and not unknown else None,
            best if known and not unknown else None,
            recorded_order=recorded_order,
            proposed_order=proposed_order if known and not unknown else (),
            proposed_timings=proposed_timings if known and not unknown else (),
            periodic_actions=rules.periodic))
    return tuple(rows)
