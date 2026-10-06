"""WAR packages from recorded resources, patch references and encounter timing."""

import re
from collections import Counter
from dataclasses import replace

from ..burst_opportunities import (
    ActionTiming,
    BurstAction,
    BurstWindow,
    GrantedAction,
    cooldown_opportunities,
    opening_clocks,
    optimize_package,
    recorded_impact_delays,
)
from ..cooldown_timing import living_windows
from ..damage import landed_fraction
from ..events import _event_name, _has_buff
from ..weaving import attach_weaves
from .buffs import INNER_RELEASE
from .bursts import POTION_ACTIONS, _own_casts, _spender_casts
from .infuriate import infuriate_timing
from .potion_alignment import annotate_potion_alignment

READY = {
    'IR spenders': (INNER_RELEASE, 'Fell Cleave'),
    'Nascent Chaos': (1001897, 'Inner Chaos'),
    'Primal Rend': (1002624, 'Primal Rend'),
    'Primal Ruination': (1003834, 'Primal Ruination'),
    'Primal Wrath': (1003901, 'Primal Wrath'),
}


def summarize_opportunities(casts, damage, buffs, life, names, actions, source, start, end,
                            windows, targetable, potion_bursts, *, ir_only=False,
                            potency_rows=(), potion_multiplier=None, potion_id=1000049):
    """Bound local additions without inventing gauge, charges or an ideal rotation.

    Resource actions require recorded grants or a feasible package that earns
    their follow-up. GCD packages compete for living,
    targetable slots using patch-specific potency and recasts. Later cleaves
    retain unknown expectations. Infuriate's variable recharge and gauge cap
    are not reconstructed, so its additional opportunities remain unknown.
    """
    own = _own_casts(casts, source)
    ir_spenders = {(e.get('packetID'), e.get('abilityGameID')) for e in damage
                   if e.get('sourceID') == source and str(INNER_RELEASE) in
                   str(e.get('buffs', '')).split('.')}
    triggers = [e['timestamp'] for e in own if _event_name(e, names) == 'Inner Release']
    for index, begin in enumerate(triggers):
        finish = triggers[index + 1] if index + 1 < len(triggers) else end
        sequence = [(e, _event_name(e, names)) for e in own if begin <= e['timestamp'] < finish]
        ir_spenders.update((e.get('packetID'), e.get('abilityGameID')) for e in
                           _spender_casts(sequence, buffs, source, begin, finish))
    known = targetable is not None and (bool(targetable.intervals) or targetable.seconds == 0)
    living = (living_windows(targetable.intervals, life, source, start, end)
              if targetable is not None and known else ())
    packet_hits = Counter((e.get('packetID'), e.get('abilityGameID')) for e in damage
                          if e.get('type') == 'damage' and e.get('sourceID') == source
                          and e.get('amount', 0) > 0
                          and not e.get('tick') and e.get('packetID') is not None)
    packet_damage = {}
    for hit in damage:
        if hit.get('type') == 'damage' and hit.get('sourceID') == source and not hit.get('tick') and hit.get('amount', 0) > 0:
            packet_damage.setdefault((hit.get('packetID'), hit.get('abilityGameID')), []).append(hit)
    delays = recorded_impact_delays(own, damage, names, source)
    ir_description = " ".join(actions.get("Inner Release", {}).get("description", ()))
    fury = re.search(r"Burgeoning Fury.*maximum of (\d+)", ir_description)
    rend_description = " ".join(actions.get("Primal Rend", {}).get("description", ()))
    ruination_duration = re.search(r"Grants Primal Ruination Ready Duration: (\d+)s", rend_description)
    result = []
    for window, burst in zip(windows, potion_bursts):
        if window.start_seconds is None or window.end_seconds is None:
            continue
        begin, finish = start + window.start_seconds * 1000, start + window.end_seconds * 1000
        within = [e for e in own if begin <= e['timestamp'] < finish]
        counts = dict(burst.casts)
        recorded_packets = dict(burst.cast_packets)
        candidates = []
        candidate_labels = {}
        uncertain = set()
        hits = {}
        actual_potency = 0.0
        for label, consumers in POTION_ACTIONS:
            selected = ([e for e in own if (e.get('packetID'), e.get('abilityGameID'))
                         in recorded_packets[label]] if label in recorded_packets else
                        [e for e in within if _event_name(e, names) in consumers
                         and (label != 'IR spenders' or
                              (e.get('packetID'), e.get('abilityGameID')) in ir_spenders)])
            if (label in READY or (not ir_only and label in {'Upheaval/Orogeny', 'Onslaught'})) and (not ir_only or label != "Nascent Chaos"):
                for event in selected:
                    data = actions.get(_event_name(event, names), {})
                    spec = data.get("potency") or {}
                    landed = packet_damage.get((event.get('packetID'), event.get('abilityGameID')), ())
                    actual_potency += sum(spec.get('base', 0) * (1 if i == 0 else
                        spec.get('falloff', {}).get('additional_target_multiplier', 1)) * landed_fraction(hit)
                        for i, hit in enumerate(landed))
            hits[label] = sum(packet_hits[e.get('packetID'), e.get('abilityGameID')] for e in selected)
            if not ir_only and label in {'Upheaval/Orogeny', 'Onslaught'}:
                data = actions.get(consumers[0], {})
                recast = data.get('recast_seconds')
                charge_match = re.search(r'Maximum Charges: (\d+)', ' '.join(data.get('description', ())))
                charges = int(charge_match[1]) if charge_match else 1
                times = tuple(e['timestamp'] for e in own if _event_name(e, names) in consumers)
                number = (cooldown_opportunities(times, recast * 1000, charges, begin, finish, living)
                          if isinstance(recast, (int, float)) and recast > 0 else None)
                if number is None:
                    uncertain.add(label)
                else:
                    previous = max((t for t in times if t < begin), default=None)
                    ready = max(begin, previous + recast * 1000) if previous is not None else min(
                        (t for t in times if begin <= t < finish), default=begin)
                    recorded = [t for t in times if begin <= t < finish]
                    for index in range(number):
                        key = f'{label}:{index}'
                        available = min(recorded[index], ready) if index < len(recorded) else ready
                        candidates.append(GrantedAction(key, available, finish, 0,
                            (data.get('potency') or {}).get('base', 0), gcd=False,
                            impact_ms=delays.get(consumers[0], 0)))
                        candidate_labels[key] = label
                        ready = available + recast * 1000
            if label not in READY or (ir_only and label == 'Nascent Chaos'):
                continue
            status, reference = READY[label]
            data = actions.get(reference, {})
            recast = data.get('recast_seconds')
            potency = (data.get('potency') or {}).get('base', 0)
            if not isinstance(recast, (int, float)) or recast <= 0:
                uncertain.add(label)
                continue
            grants = [e for e in buffs if e.get('targetID') == source
                      and e.get('sourceID') in {source, None}
                      and e.get('abilityGameID') == status
                      and e.get('type') in {'applybuff', 'refreshbuff'}
                      and e['timestamp'] < finish]
            for index, grant in enumerate(sorted(grants, key=lambda e: e['timestamp'])):
                time = grant['timestamp']
                parent = next((e for e in own if grant.get('packetID') is not None
                               and e.get('packetID') == grant.get('packetID')
                               and e.get('abilityGameID') == grant.get('extraAbilityGameID')), None)
                if (label == 'Primal Ruination' and ruination_duration and parent is not None
                        and begin <= parent['timestamp'] < finish
                        and any(candidate_labels[c.name] == 'Primal Rend' for c in candidates)):
                    continue
                if (label == 'Primal Wrath' and fury and 'Wrathful' in ir_description
                        and any(c.name.startswith('IR spenders:') and c.available <= time
                                for c in candidates)):
                    continue
                available = max(begin, time)
                # A GCD follow-up granted by a recorded GCD cannot start until
                # that cast's recast ends. Its grant time is not a free GCD slot.
                if data.get('type', '').casefold() in {'spell', 'weaponskill'}:
                    parent = next((e for e in own
                                   if grant.get('packetID') is not None
                                   and e.get('packetID') == grant.get('packetID')
                                   and e.get('abilityGameID') == grant.get('extraAbilityGameID')),
                                  None)
                    if parent is not None:
                        parent_data = actions.get(_event_name(parent, names), {})
                        parent_recast = parent_data.get('recast_seconds')
                        if (parent_data.get('type', '').casefold() in {'spell', 'weaponskill'}
                                and isinstance(parent_recast, (int, float))):
                            available = max(available, parent['timestamp'] + parent_recast * 1000)
                duration = grant.get('duration')
                if not isinstance(duration, (int, float)):
                    if time >= begin:
                        uncertain.add(label)
                    continue
                deadline = min(end, time + duration)
                for event in life:
                    if (event.get('type') == 'death' and event.get('targetID') == source
                            and time <= event['timestamp']):
                        deadline = min(deadline, event['timestamp'])
                next_grant = min((e['timestamp'] for e in grants if e['timestamp'] > time),
                                 default=deadline)
                deadline = min(deadline, next_grant)
                if available >= min(finish, deadline):
                    continue
                consumed = [e for e in own if time <= e['timestamp'] < deadline
                            and _event_name(e, names) in consumers
                            and (label != 'IR spenders' or
                                 (e.get('packetID'), e.get('abilityGameID')) in ir_spenders)]
                if any(packet_hits[e.get('packetID'), e.get('abilityGameID')] > 1
                       for e in consumed if e['timestamp'] >= finish):
                    uncertain.add(label)
                    continue
                # Removed grants do not become available again. Consumption at
                # the removal timestamp is still counted as recorded evidence.
                removed = min((e['timestamp'] for e in buffs if e.get('targetID') == source
                               and e.get('abilityGameID') == status
                               and e.get('type') == 'removebuff' and time < e['timestamp'] < begin),
                              default=None)
                if removed is not None:
                    continue
                stacks = 1
                if label == 'IR spenders':
                    description = ' '.join(actions.get('Inner Release', {}).get('description', ()))
                    match = re.search(r'Grants (\d+) stacks of Inner Release', description)
                    if match is None:
                        uncertain.add(label)
                        continue
                    stacks = int(match[1])
                remaining = max(0, stacks - sum(e['timestamp'] < begin for e in consumed))
                for charge in range(remaining):
                    key = f'{label}:{index}:{charge}'
                    predecessor = f'{label}:{index}:{charge - 1}' if label == 'IR spenders' and charge else None
                    candidates.append(GrantedAction(
                        key, available, min(finish, deadline), recast * 1000, potency, predecessor,
                        gcd=data.get('type', '').casefold() != 'ability',
                        impact_ms=delays.get(reference, 0),
                    ))
                    candidate_labels[key] = label
                if remaining and label == 'Primal Rend' and ruination_duration:
                    key = f'Primal Ruination:earned:{index}'
                    reference = actions.get('Primal Ruination', {})
                    candidates.append(GrantedAction(
                        key, begin, min(finish, min((e['timestamp'] for e in life
                            if e.get('type') == 'death' and e.get('targetID') == source
                            and e['timestamp'] >= time), default=finish)),
                        reference.get('recast_seconds', 2.5) * 1000,
                        (reference.get('potency') or {}).get('base', 0),
                        f'Primal Rend:{index}:0', impact_ms=delays.get('Primal Ruination', 0),
                        unlock_duration_ms=int(ruination_duration[1]) * 1000,
                    ))
                    candidate_labels[key] = 'Primal Ruination'
                if (label == 'IR spenders' and fury and 'Wrathful' in ir_description
                        and remaining == int(fury[1]) and 'Primal Wrath' in actions):
                    key = f'Primal Wrath:earned:{index}'
                    reference = actions['Primal Wrath']
                    candidates.append(GrantedAction(
                        key, begin, min(finish, deadline), 0,
                        (reference.get('potency') or {}).get('base', 0),
                        f'IR spenders:{index}:{remaining - 1}', gcd=False,
                        impact_ms=delays.get('Primal Wrath', 0),
                        unlock_duration_ms=recast * 1000,
                    ))
                    candidate_labels[key] = 'Primal Wrath'
        scope = {name for label, consumers in POTION_ACTIONS
                 if not ir_only or label in {'IR spenders', 'Primal Rend', 'Primal Ruination', 'Primal Wrath'}
                 for name in consumers}
        animation_ready, gcd_start = opening_clocks(casts, names, actions, source, begin, scope)
        aliases = {name: label for label, consumers in POTION_ACTIONS for name in consumers}
        candidates, candidate_labels, fixed_weaves = attach_weaves(candidates, candidate_labels,
            own, names, actions, begin, finish, aliases,
            {(e.get('packetID'), e.get('abilityGameID')) for e in own
             if _event_name(e, names) in {'Fell Cleave', 'Decimate'}
             and (e.get('packetID'), e.get('abilityGameID')) not in ir_spenders},
            fixed_names=('Inner Release', 'Infuriate'))
        from ..gcd_budget import recorded_gcd_budget
        budget = recorded_gcd_budget(casts, names, actions, source, begin, finish, living,
                                     begin, delays)
        animation_ready, gcd_start = opening_clocks(
            casts, names, actions, source, begin, scope, budget.recast_ms)
        budget = replace(budget, ready=max(animation_ready, gcd_start))
        candidates = tuple(replace(c, recast_ms=budget.recast_ms)
                           if c.gcd and c.recast_ms == 2500 else c for c in candidates)
        plan = optimize_package(tuple(candidates), living, animation_ready, finish, gcd_ready=gcd_start,
            impact_windows=targetable.intervals if targetable is not None else (),
            fixed_weaves=fixed_weaves, gcd_budget=budget)
        expected = Counter(candidate_labels[key] for key, _ in plan.casts)
        best_potency = plan.potency
        recorded_order = tuple((_event_name(e, names), (e['timestamp'] - start) / 1000)
                               for e in within if _event_name(e, names) in scope)
        proposed_order = tuple((candidate_labels[key], (time - start) / 1000)
                               for key, time in plan.casts)
        proposed_order += tuple((candidate_labels[key], (time - start) / 1000) for key, time in plan.weaves)
        proposed_order = tuple(sorted(proposed_order, key=lambda row: row[1]))
        candidate_by_key = {c.name: c for c in candidates}
        consumers_by_label = dict(POTION_ACTIONS)
        proposed_timings = tuple(ActionTiming(candidate_labels[key], (time - start) / 1000,
            ((time + candidate_by_key[key].impact_ms - start) / 1000,)
            if any(n in delays for n in consumers_by_label.get(candidate_labels[key], ())) else (), True)
            for key, time in plan.casts if candidate_labels[key] != 'Infuriate')
        proposed_timings += tuple(ActionTiming(candidate_labels[key], (time - start) / 1000,
            ((time + delays[candidate_labels[key]] - start) / 1000,)
            if candidate_labels[key] in delays else (), True)
            for key, time in plan.weaves if actions.get(candidate_labels[key], {}).get('potency'))
        # A recorded landed package is itself feasible. Keep the whole package
        # as a fallback when missing timing/resource evidence understates it.
        if actual_potency >= best_potency:
            expected = Counter({label: counts.get(label, 0) for label, _ in POTION_ACTIONS
                                if label != 'Infuriate' and (not ir_only or
                                    label in {'IR spenders', 'Primal Rend', 'Primal Ruination', 'Primal Wrath'})})
            best_potency = actual_potency
            proposed_order = recorded_order
            proposed_timings = ()
        inferred_wrath = any(key.startswith('Primal Wrath:earned:') for key, _ in plan.casts)
        rows = []
        infuriate = infuriate_timing(casts, damage, names, actions, source,
                                     begin, finish, end) if not ir_only else None
        for label, consumers in POTION_ACTIONS:
            review = False
            actual = counts.get(label, 0)
            opportunity = None
            if known and label in READY and label not in uncertain:
                opportunity = expected[label]
                # Missing grants do not establish resources unless the chosen
                # package can earn them. Recorded casts remain a lower bound.
                if not actual and not any(candidate_labels[c.name] == label for c in candidates) and not any(e.get('abilityGameID') == READY[label][0]
                                          and e.get('targetID') == source
                                          and e['timestamp'] < finish for e in buffs):
                    opportunity = None
            elif known and label in {'Upheaval/Orogeny', 'Onslaught'} and label not in uncertain:
                opportunity = expected[label]
            notes = (("Primal Wrath could be earned by completing the Inner Release spender package.",)
                     if label == 'Primal Wrath' and inferred_wrath
                     and not any(e.get('abilityGameID') == READY[label][0]
                                 and e.get('targetID') == source and begin <= e['timestamp'] < finish
                                 for e in buffs)
                     and opportunity is not None and actual < opportunity else ())
            if label == 'Infuriate' and not ir_only:
                timing = infuriate
                evidence = []
                if timing is not None and timing.opening_charges is not None:
                    evidence.append(f"Charges available at potion start: {timing.opening_charges}.")
                if timing is not None and timing.closing_charges == 0 and timing.next_charge_after_end is not None:
                    evidence.append("The next charge became available "
                                    f"{timing.next_charge_after_end:.1f}s after the potion ended "
                                    "on the recorded timeline.")
                elif timing is not None and timing.closing_charges is not None:
                    evidence.append(f"Charges available at potion end: {timing.closing_charges}.")
                if evidence:
                    evidence.append("Landed spenders shorten recharge. An earlier Infuriate still needs "
                                    "gauge room and time to spend Nascent Chaos. Extra uses are not assumed.")
                notes += tuple(evidence)
            if label == 'Nascent Chaos' and infuriate is not None:
                preceding = sorted((e for e in buffs if e.get('targetID') == source
                    and e.get('abilityGameID') == READY[label][0]
                    and e.get('type') in {'applybuff', 'refreshbuff', 'removebuff'}
                    and e['timestamp'] < begin), key=lambda e: e['timestamp'])
                first_use = min((e['timestamp'] for e in within
                                 if _event_name(e, names) == 'Infuriate'), default=None)
                if (preceding and preceding[-1]['type'] == 'removebuff'
                        and infuriate.opening_charges_minimum > 0 and first_use is not None
                        and first_use > begin and actual > 0
                        and actual == counts.get('Infuriate', 0)):
                    review = True
                    note = ("No Nascent Chaos carried into this potion despite at least "
                              f"{infuriate.opening_charges_minimum} available Infuriate "
                              f"{'charge' if infuriate.opening_charges_minimum == 1 else 'charges'}. "
                              f"Infuriate was first used {(first_use - begin) / 1000:.1f}s "
                              "after the window started. Check using Infuriate before the potion "
                              "to carry a grant in. A third NC use still needs gauge room and a GCD slot.")
                    notes += (note,)
            rows.append(BurstAction(label, actual, hits[label], opportunity, notes, review))
        calculated = BurstWindow(window.start_seconds, window.end_seconds, tuple(rows),
                                  burst.base_potency + burst.gained_potency,
                                  actual_potency if known and not uncertain else None,
                                  best_potency if known and not uncertain else None,
                                  recorded_order=recorded_order,
                                  proposed_order=proposed_order if known and not uncertain else (),
                                  proposed_timings=proposed_timings if known and not uncertain else ())
        if not ir_only:
            calculated = annotate_potion_alignment(calculated, casts, buffs, names, actions,
                source, start, end, burst.cast_packets, life, damage=damage,
                potion_id=potion_id, potency_rows=potency_rows, potion_multiplier=potion_multiplier)
        result.append(calculated)
    return tuple(result)


def summarize_ir_opportunities(casts, damage, buffs, life, names, actions, source, start, end,
                               targetable, bursts, combatants=()):
    """Evaluate each recorded IR sequence using its grants, including later impacts."""
    from dataclasses import replace

    from ..models import PotionWindow
    from .bursts import WarPotionBurst

    windows = []
    counts = []
    own = _own_casts(casts, source)
    for index, burst in enumerate(bursts):
        begin = burst.seconds if burst.seconds is not None else 0.0
        finish = (bursts[index + 1].seconds if index + 1 < len(bursts) else (end - start) / 1000)
        if finish is None or finish <= begin:
            continue
        windows.append(PotionWindow(begin, finish))
        sequence_begin = (start + begin * 1000 if burst.seconds is not None else
                          min(start, min((e['timestamp'] for e in own), default=start)))
        sequence_end = start + finish * 1000
        sequence = [e for e in own if sequence_begin <= e['timestamp'] < sequence_end]
        spenders = _spender_casts([(e, _event_name(e, names)) for e in sequence], buffs,
                                  source, sequence_begin, sequence_end, burst.seconds is None)
        rend = [e for e in sequence if _event_name(e, names) == 'Primal Rend'
                and (burst.seconds is None or e['timestamp'] < sequence_begin + 30000)]
        ruination = [e for e in sequence if _event_name(e, names) == 'Primal Ruination'
                     and any(r['timestamp'] <= e['timestamp'] < r['timestamp'] + 20000 for r in rend)]
        wrath = [e for e in sequence if _event_name(e, names) == 'Primal Wrath']
        packets = tuple((label, tuple((e['packetID'], e['abilityGameID']) for e in events
                                     if isinstance(e.get('packetID'), int)
                                     and isinstance(e.get('abilityGameID'), int)))
                        for label, events in (('IR spenders', spenders), ('Primal Rend', rend),
                                              ('Primal Ruination', ruination), ('Primal Wrath', wrath)))
        counts.append(WarPotionBurst(begin, finish, (
            ('IR spenders', burst.spenders), ('Primal Rend', burst.rend),
            ('Primal Ruination', burst.ruination), ('Primal Wrath', burst.wrath),
        ), 0, 0, 0, packets))
    rows = summarize_opportunities(casts, damage, buffs, life, names, actions, source, start, end,
                                   windows, targetable, counts, ir_only=True)
    opening = {a.get('ability') for c in combatants if c.get('sourceID') == source
               for a in c.get('auras', ())}
    result = []
    for index, row in enumerate(rows):
        selected = []
        for action in row.actions:
            if action.name not in {'IR spenders', 'Primal Rend', 'Primal Ruination', 'Primal Wrath'}:
                continue
            if bursts[index].seconds is None:
                expected = None
                finish = start + row.end_seconds * 1000
                if action.name == 'IR spenders':
                    description = ' '.join(actions.get('Inner Release', {}).get('description', ()))
                    match = re.search(r'Grants (\d+) stacks of Inner Release', description)
                    spenders = [e for e in own if e['timestamp'] < finish
                                and _event_name(e, names) in {'Fell Cleave', 'Decimate'}]
                    # Snapshots identify IR spending, unlike a lucky DH/Crit.
                    # Stack removals can also prove consumption when a hit ghosts.
                    confirmed = [e for e in spenders if any(
                        hit.get('sourceID') == source and _has_buff(hit, INNER_RELEASE)
                        and hit.get('type') in {'damage', 'calculateddamage'}
                        and e.get('packetID') is not None
                        and (hit.get('packetID'), hit.get('abilityGameID'))
                        == (e.get('packetID'), e.get('abilityGameID')) for hit in damage
                    ) or any(
                        buff.get('targetID') == source and buff.get('abilityGameID') == INNER_RELEASE
                        and buff.get('type') == 'removebuffstack'
                        and isinstance(buff.get('stack'), int)
                        and abs(buff['timestamp'] - e['timestamp']) <= 100 for buff in buffs
                    )]
                    if match and action.casts == int(match[1]) and len(confirmed) == action.casts:
                        expected = action.casts
                elif action.name == 'Primal Rend':
                    if 1002624 in opening and action.casts == 1:
                        expected = 1
                else:
                    status = READY[action.name][0]
                    if any(e.get('targetID') == source and e.get('abilityGameID') == status
                           and e.get('type') in {'applybuff', 'refreshbuff'}
                           and start <= e['timestamp'] < finish for e in buffs):
                        expected = action.expected
                action = replace(action, expected=expected)
            selected.append(action)
        result.append(replace(row, actions=tuple(selected),
                              actual_package_potency=(None if bursts[index].seconds is None
                                                      else row.actual_package_potency),
                              best_package_potency=(None if bursts[index].seconds is None
                                                    else row.best_package_potency)))
    return tuple(result)
