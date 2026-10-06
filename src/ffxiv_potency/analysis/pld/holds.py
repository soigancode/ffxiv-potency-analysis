"""Bounded Blade holds at witnessed cleave timings, preserving other recorded actions."""

import re
from dataclasses import replace
from functools import cache

from ..burst_opportunities import (
    ActionTiming,
    BurstWindow,
    GrantedAction,
    HoldAction,
    HoldComparison,
    expected_periodic_damage,
    opening_clocks,
    recorded_impact_delays,
)
from ..events import _event_name
from ..gcd_budget import gcd_capacity, recorded_gcd_budget
from ..penalties import penalty_multiplier, revival_multiplier
from ..targetability import TargetableTime
from .state import BLADES, replay_spells


def compare_holds(windows: tuple[BurstWindow, ...], casts, damage, potency_rows, names,
                  actions, source, start, end, targetable: TargetableTime | None, life,
                  buffs, debuffs, combatants, self_windows, profile,
                  penalty_rules, periodic_target_windows=None) -> tuple[BurstWindow, ...]:
    """Compare early uses and legal holds without replacing future GCDs or weaves.

    Multi-target casts establish cleave positions only at their recorded times.
    Empty future slots and slots freed by this burst's own held actions may be
    used. Other bursts and resource generation remain fixed. This is a local
    comparison, not a full-fight rotation search.
    """
    if targetable is None or not targetable.intervals:
        return windows
    periodic_target_windows = periodic_target_windows or {}
    own = sorted((e for e in casts if e.get('sourceID') == source and e.get('type') == 'cast'
                  and not e.get('fake')), key=lambda e: e['timestamp'])
    own = list({(e.get('packetID', e['timestamp']), e.get('abilityGameID')): e for e in own}.values())
    packets = {}
    for hit in damage:
        if hit.get('sourceID') == source and not hit.get('tick') and hit.get('amount', 0) > 0:
            packets.setdefault((hit.get('packetID'), hit.get('abilityGameID')), []).append(hit)
    values = {}
    for hit, _, _, value in potency_rows:
        if not hit.get('tick'):
            key = hit.get('packetID'), hit.get('abilityGameID')
            values[key] = values.get(key, 0) + value
    delays = recorded_impact_delays(own, damage, names, source)
    witnesses = []
    witness_targets = {}
    for event in own:
        name = _event_name(event, names)
        if name not in {*BLADES, 'Blade of Honor', 'Holy Circle'}:
            continue
        hits = packets.get((event.get('packetID'), event.get('abilityGameID')), ())
        targets = {(h.get('targetID'), h.get('targetInstance', 1)) for h in hits}
        if len(targets) > 1:
            witnesses.append((event['timestamp'], len(targets)))
            witness_targets[event['timestamp']] = targets
    if not witnesses:
        return windows
    initial = {a['ability']: start + a.get('duration', 0) for c in combatants
               if c.get('sourceID') == source for a in c.get('auras', ())
               if 'ability' in a and isinstance(a.get('duration'), (int, float))}
    statuses = sorted((e for e in (*buffs, *debuffs) if e.get('targetID') == source),
                      key=lambda e: e['timestamp'])

    @cache
    def modifier(time):
        active = dict(initial)
        for event in statuses:
            if event['timestamp'] > time:
                break
            status = event.get('abilityGameID')
            kind = event.get('type')
            if kind in {'applybuff', 'refreshbuff', 'applydebuff', 'refreshdebuff'}:
                duration = event.get('duration')
                active[status] = (event['timestamp'] + duration if isinstance(duration, (int, float))
                                  else float('inf'))
            elif kind in {'removebuff', 'removedebuff'}:
                active.pop(status, None)
        present = {s for s, expiry in active.items() if time < expiry}
        evidence = {'buffs': '.'.join(str(s) for s in present)}
        factor = penalty_multiplier(evidence, penalty_rules) * revival_multiplier(evidence, profile)
        if profile.potion_buff_id in present:
            factor *= profile.player_potion_multiplier
        for intervals in self_windows.values():
            factor *= next((strength for a, b, strength in intervals if a <= time < b), 1)
        return factor

    state = replay_spells(casts, buffs, life, combatants, names, source, start, end)
    divine = {(s.packet, s.ability_id) for s in state.spells if s.enhancement == 'Divine Might'}
    description = ' '.join(actions.get('Imperator', {}).get('description', ()))
    count_match = re.search(r'Grants (\d+) stacks of Requiescat', description)
    duration_match = re.search(r'Requiescat Duration: (\d+)s', description)
    charges = int(count_match[1]) if count_match else 4
    req_duration = int(duration_match[1]) * 1000 if duration_match else 30000
    honor_text = ' '.join(actions.get('Blade of Valor', {}).get('description', ()))
    honor_match = re.search(r'Duration: (\d+)s', honor_text)
    honor_duration = int(honor_match[1]) * 1000 if honor_match else 30000
    def evaluate(window: BurstWindow) -> BurstWindow:
        proposed = dict(window.proposed_order)
        begin, finish = start + window.start_seconds * 1000, start + window.end_seconds * 1000
        root = next((e for e in own if begin <= e['timestamp'] < finish
                     and _event_name(e, names) == 'Confiteor'), None)
        required = (*BLADES[1:], 'Blade of Honor')
        if root is None or not all(n in proposed for n in ('Imperator', *BLADES, 'Blade of Honor')):
            return window
        next_root = min((e['timestamp'] for e in own if e['timestamp'] > root['timestamp']
                         and _event_name(e, names) == 'Confiteor'), default=end)
        next_valor = min((e['timestamp'] for e in own if e['timestamp'] >= next_root
                          and _event_name(e, names) == 'Blade of Valor'), default=end)
        horizon = min(end, next_valor)
        if not any(finish <= t < horizon for t, _ in witnesses):
            return window
        recorded = {name: next((e for e in own if root['timestamp'] < e['timestamp'] < (
            next_root if name in BLADES else next_valor) and _event_name(e, names) == name), None)
            for name in required}
        if any(recorded[n] is None for n in required):
            return window
        origin = {(e.get('packetID'), e.get('abilityGameID')) for e in recorded.values() if e is not None}
        fixed = [e for e in own if finish <= e['timestamp'] < horizon
                 and (e.get('packetID'), e.get('abilityGameID')) not in origin]
        fixed_gcds = []
        fixed_abilities = []
        for e in fixed:
            spec = actions.get(_event_name(e, names), {})
            time = e['timestamp']
            if spec.get('type', '').casefold() in {'spell', 'weaponskill'}:
                cast_time = (spec.get('cast_seconds') or 0) * 1000
                time = max((c['timestamp'] for c in casts if c.get('sourceID') == source
                    and c.get('type') == 'begincast' and c.get('abilityGameID') == e.get('abilityGameID')
                    and time - cast_time - 250 <= c['timestamp'] <= time), default=time)
                fixed_gcds.append(time)
            else:
                # Role actions may be absent from the job reference. Their
                # recorded animation locks still occupy future weave slots.
                fixed_abilities.append(time)
        budget = recorded_gcd_budget(casts, names, actions, source, begin, finish,
                                     targetable.intervals, begin, delays)
        recast = budget.recast_ms
        animation, gcd = opening_clocks(casts, names, actions, source, begin,
                                       {a.name for a in window.actions}, recast)
        budget = replace(budget, ready=max(animation, gcd),
            windows=tuple((a, min(b, finish)) for a, b in budget.windows))
        imperator = start + proposed['Imperator'] * 1000
        req_end = min(imperator + req_duration,
            min((e['timestamp'] for e in own if e['timestamp'] > imperator + 1500
                 and _event_name(e, names) == 'Imperator'), default=end))
        external = [e['timestamp'] for e in own if imperator <= e['timestamp'] < req_end
                    and _event_name(e, names) in {*BLADES, 'Holy Spirit', 'Holy Circle', 'Clemency'}
                    and (not begin <= e['timestamp'] < finish
                         or _event_name(e, names) not in proposed)
                    and (e.get('packetID'), e.get('abilityGameID')) not in origin
                    and (e.get('packetID'), e.get('abilityGameID')) not in divine]
        deaths = [e['timestamp'] for e in life if e.get('targetID') == source and e.get('type') == 'death']
        req_end = min(req_end, min((t for t in deaths if t >= imperator), default=end))
        points = {}
        for name in required:
            original = start + proposed[name] * 1000
            future = []
            for time, targets in witnesses:
                if not finish <= time < (next_root if name in BLADES else horizon):
                    continue
                # Reusing an authoritative recorded slot retains its actual
                # animation spacing, which can be shorter than the 700ms
                # estimate used for hypothetical insertions.
                recorded_slot = any(e is not None and e['timestamp'] == time
                    and ((_event_name(e, names) in BLADES) == (name in BLADES))
                    for e in recorded.values())
                if not recorded_slot and any(abs(time - t) < 700 - .001 for t in fixed_abilities):
                    continue
                clearance = recast if name in BLADES else 700
                if not recorded_slot and any(abs(time - t) < clearance - .001 for t in fixed_gcds):
                    continue
                if not any(a <= time + delays.get(name, 0) < b for a, b in targetable.intervals):
                    continue
                impact = time + delays.get(name, 0)
                targets = sum(any(a <= impact < b for a, b in
                    periodic_target_windows.get(target, targetable.intervals))
                    for target in witness_targets[time])
                if targets < 2:
                    continue
                future.append((time, targets))
            points[name] = tuple(sorted({(original, 1), *future}))

        def potency(name, time, targets, earlier):
            spec = actions[name]['potency']
            base = spec['base']
            enhanced = False
            used = sum(t <= time for t in external) + sum(t <= time for n, t, _ in earlier if n in BLADES)
            if name in BLADES and imperator <= time < req_end and used < charges:
                base = spec.get('conditional_potencies', {}).get('Requiescat', base)
                enhanced = True
            falloff = spec.get('falloff', {}).get('additional_target_multiplier', 1)
            return base * (1 + (targets - 1) * falloff) * modifier(time), enhanced

        conf = ('Confiteor', start + proposed['Confiteor'] * 1000, 1)
        inside: list[tuple[str, float, int]] = [conf]
        inside_values: dict[str, float] = {}
        inside_enhancements: dict[str, bool] = {}
        for name in required:
            time = start + proposed[name] * 1000
            inside_values[name], inside_enhancements[name] = potency(name, time, 1, inside)
            inside.append((name, time, 1))
        baseline = sum(inside_values.values())
        best = baseline
        best_order: tuple[tuple[str, float, int], ...] = tuple(inside[1:])
        best_values = dict(inside_values)
        best_enhancements = dict(inside_enhancements)
        # Fixed inside-burst actions retain their chosen positions.
        occupied = [(name, start + t * 1000) for name, t in window.proposed_order
                    if name not in required]
        specs = {name: GrantedAction(name, begin, horizon, recast,
            (actions.get(name, {}).get('potency') or {}).get('base', 0),
            gcd=actions.get(name, {}).get('type', '').casefold() in {'spell', 'weaponskill'},
            impact_ms=delays.get(name, 0)) for name, _ in occupied}
        specs.update({name: GrantedAction(name, begin, horizon, recast, actions[name]['potency']['base'],
            gcd=name in BLADES, impact_ms=delays.get(name, 0)) for name in required})
        baseline_count = gcd_capacity(budget, (*occupied,
            *((name, time) for name, time, _ in best_order)), specs)[0]

        def visit(index, order, total, scored, enhanced):
            nonlocal best, best_order, best_values, best_enhancements
            if index == len(required):
                schedule = tuple(sorted((*occupied, *((n, t) for n, t, _ in order)), key=lambda r: r[1]))
                counts = gcd_capacity(budget, schedule, specs)[0]
                if len(counts) != len(baseline_count) or any(a < b for a, b in zip(counts, baseline_count)):
                    return
                if total > best + .001:
                    best, best_order, best_values, best_enhancements = total, tuple(order), dict(scored), dict(enhanced)
                return
            name = required[index]
            previous = conf[1] if not order else order[-1][1]
            spacing = recast if name in BLADES else 700
            expiry = previous + (30000 if name in BLADES else honor_duration)
            eligible = [(t, n) for t, n in points[name] if previous + spacing <= t + .001 < expiry
                        and not any(previous < d <= t for d in deaths)]
            for time, targets in eligible:
                if any(abs(time - t) < (recast if specs[n].gcd and name in BLADES else 700) - .001
                       for n, t in occupied if n != 'Confiteor' or time < t):
                    continue
                value, enhancement = potency(name, time, targets, (conf, *order))
                # Optimistic suffix bound: assume full charges at each future
                # point while respecting expiry and witnessed target counts.
                upper = total + value
                for remaining in required[index + 1:]:
                    choices = [(t, n) for t, n in points[remaining] if t >= time + 700]
                    upper += max((potency(remaining, t, n, (conf,))[0] for t, n in choices), default=0)
                if upper <= best + .001:
                    continue
                visit(index + 1, (*order, (name, time, targets)), total + value,
                      {**scored, name: value}, {**enhanced, name: enhancement})

        visit(0, (), 0, {}, {})
        changed = [name for name, time, _ in best_order if time >= finish]
        actual_held = [name for name, event in recorded.items() if event is not None and event['timestamp'] >= finish]
        relevant = tuple(n for n in required if n in changed or n in actual_held)
        if not relevant:
            return window
        selected = {name: (time, targets) for name, time, targets in best_order}
        rows = []
        for name in relevant:
            event = recorded[name]
            assert event is not None
            value = values.get((event.get('packetID'), event.get('abilityGameID')))
            if value is None:
                break
            time, targets = selected[name]
            rows.append(HoldAction(name, inside_values[name], value, best_values[name],
                (time - start) / 1000, targets, 'Requiescat' if best_enhancements.get(name) else 'None'))
        else:
            comparison = HoldComparison(tuple(rows), sum(r.inside_potency for r in rows),
                sum(r.recorded_potency for r in rows), sum(r.proposed_potency for r in rows))
            new_order = tuple(sorted((*((n, t) for n, t in window.proposed_order if n not in required),
                *((name, (time - start) / 1000) for name, time, _ in best_order)), key=lambda r: r[1]))
            timings = tuple(t for t in window.proposed_timings if t.name not in required)
            timings += tuple(ActionTiming(name, (time - start) / 1000,
                ((time + delays.get(name, 0) - start) / 1000,), True) for name, time, _ in best_order)
            scope = {a.name for a in window.actions}
            def direct(name, time):
                spec = actions.get(name, {}).get('potency') or {}
                base = spec.get('base', 0)
                event = next((e for e in own if _event_name(e, names) == name
                              and abs(e['timestamp'] - time) < .002), None)
                hits = packets.get((event.get('packetID'), event.get('abilityGameID')), ()) if event else ()
                targets = len({(h.get('targetID'), h.get('targetInstance', 1)) for h in hits}) or 1
                return base * (1 + (targets - 1) * spec.get('falloff', {}).get('additional_target_multiplier', 1)) * modifier(time)

            def ticks(name, time):
                if name not in window.periodic_actions:
                    return 0
                dot = actions[name]['potency'].get('damage_over_time', {})
                event = next((e for e in own if _event_name(e, names) == name
                              and abs(e['timestamp'] - time) < .002), None)
                hits = packets.get((event.get('packetID'), event.get('abilityGameID')), ()) if event else ()
                targets = {(h.get('targetID'), h.get('targetInstance', 1)) for h in hits}
                falloff = actions[name]['potency'].get('falloff', {}).get('additional_target_multiplier', 1)
                value = 0
                for index, target in enumerate(sorted(targets) if targets else ((None, 1),)):
                    action = GrantedAction(name, 0, 0, 0, 0,
                        tick_potency=dot.get('potency_per_tick', 0) * (1 if index == 0 else falloff),
                        dot_duration_ms=dot.get('duration_seconds', 0) * 1000)
                    hit = next((h for h in hits if
                        (h.get('targetID'), h.get('targetInstance', 1)) == target), None)
                    fraction = (hit['amount'] / (hit['amount'] + max(0, hit.get('overkill', 0)))
                                if hit is not None else 1)
                    value += expected_periodic_damage(action, time + delays.get(name, 0),
                        periodic_target_windows.get(target, targetable.intervals))[0] * fraction
                return value * modifier(time)

            fixed_value = sum(direct(n, t) + ticks(n, t) for n, t in occupied
                              if n in scope and n != 'Confiteor')
            fixed_value += potency('Confiteor', conf[1], 1, ())[0]
            actual = 0
            for name, seconds in window.recorded_order:
                if name not in scope:
                    continue
                time = start + seconds * 1000
                event = next((e for e in own if _event_name(e, names) == name
                              and abs(e['timestamp'] - time) < .002), None)
                if event is not None:
                    actual += values.get((event.get('packetID'), event.get('abilityGameID')), 0)
                    actual += ticks(name, time)
            full_best = max(actual, fixed_value + best)
            if actual > fixed_value + best + .05:
                # The recorded package is an authoritative lower bound. If
                # it wins, its order must accompany its score.
                new_order, timings = window.recorded_order, window.recorded_timings
                rows = []
                for row in comparison.actions:
                    event = recorded[row.name]
                    assert event is not None
                    hits = packets.get((event.get('packetID'), event.get('abilityGameID')), ())
                    enhancement = next((s.enhancement for s in state.spells
                        if s.packet == event.get('packetID') and s.ability_id == event.get('abilityGameID')), 'None')
                    rows.append(replace(row, proposed_potency=row.recorded_potency,
                        cast_seconds=(event['timestamp'] - start) / 1000,
                        targets=len({(h.get('targetID'), h.get('targetInstance', 1)) for h in hits}),
                        enhancement=enhancement))
                comparison = replace(comparison, actions=tuple(rows),
                    proposed_potency=comparison.recorded_potency)
            return replace(window, hold_comparison=comparison,
                proposed_order=new_order, proposed_timings=timings,
                inside_package_potency=fixed_value + baseline,
                actual_package_potency=actual, best_package_potency=full_best,
                actions=tuple(replace(a, expected=1) if a.name in required else a for a in window.actions))
        return window
    return tuple(evaluate(window) for window in windows)
