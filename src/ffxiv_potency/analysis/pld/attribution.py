"""Keep delayed follow-ups with the burst that provided their ready effect."""

from dataclasses import replace

from ..burst_opportunities import ActionTiming, HeldCast
from ..events import _event_name
from .state import BLADES


def attribute_followups(windows, casts, buffs, damage, names, source, start):
    windows = list(windows)
    own = sorted((e for e in casts if e.get('sourceID') == source
                  and e.get('type') == 'cast' and not e.get('fake')), key=lambda e: e['timestamp'])
    own = list({(e.get('packetID', e['timestamp']), e.get('abilityGameID')): e for e in own}.values())
    packets = {}
    for hit in damage:
        if (hit.get('sourceID') == source and hit.get('type') == 'damage'
                and not hit.get('tick') and hit.get('amount', 0) > 0):
            packets.setdefault((hit.get('packetID'), hit.get('abilityGameID')), []).append(hit)

    def physical(time):
        return next((i for i, w in enumerate(windows)
                     if w.start_seconds <= (time - start) / 1000 < w.end_seconds), None)

    def grant_owner(event, status):
        grants = [g for g in buffs if g.get('targetID') == source
                  and g.get('sourceID') in {source, None} and g.get('abilityGameID') == status
                  and g.get('type') in {'applybuff', 'refreshbuff'} and g['timestamp'] <= event['timestamp']
                  and isinstance(g.get('duration'), (int, float))
                  and event['timestamp'] < g['timestamp'] + g['duration']]
        grant = max(grants, key=lambda g: g['timestamp'], default=None)
        if grant is None:
            return physical(event['timestamp'])
        parent = next((c for c in own if grant.get('packetID') is not None
                       and c.get('packetID') == grant['packetID']
                       and c.get('abilityGameID') == grant.get('extraAbilityGameID')), None)
        owner = physical(parent['timestamp']) if parent is not None else None
        return owner if owner is not None else physical(grant['timestamp'])

    ownership = {}
    current_owner = None
    honor_owner = None
    honor_expiry = float('-inf')
    for event in own:
        name = _event_name(event, names)
        time = event['timestamp']
        if name == BLADES[0]:
            current_owner = grant_owner(event, 1003019)
        if name in BLADES:
            ownership[event.get('packetID', time), event.get('abilityGameID')] = current_owner
        if name == 'Blade of Valor':
            honor_owner = current_owner
            grant = next((g for g in buffs if g.get('targetID') == source
                          and g.get('abilityGameID') == 1003831
                          and g.get('type') in {'applybuff', 'refreshbuff'}
                          and time <= g['timestamp'] < time + 1500), None)
            honor_expiry = (grant['timestamp'] + grant['duration'] if grant is not None
                            and isinstance(grant.get('duration'), (int, float)) else time)
        elif name == 'Blade of Honor':
            if time < honor_expiry:
                ownership[event.get('packetID', time), event.get('abilityGameID')] = honor_owner
            honor_expiry = float('-inf')
        elif name == 'Goring Blade':
            ownership[event.get('packetID', time), event.get('abilityGameID')] = grant_owner(event, 1003847)

    for event in own:
        key = event.get('packetID', event['timestamp']), event.get('abilityGameID')
        owner = ownership.get(key)
        recipient = physical(event['timestamp'])
        if owner is None or owner == recipient:
            continue
        name = _event_name(event, names)
        seconds = (event['timestamp'] - start) / 1000
        hits = len(packets.get((event.get('packetID'), event.get('abilityGameID')), ()))
        w = windows[owner]
        windows[owner] = replace(w,
            actions=tuple(replace(a, casts=a.casts + 1, hits=a.hits + hits,
                                  expected=max(a.expected or 0, a.package_casts + 1))
                          if a.name == name else a for a in w.actions),
            held_casts=(*w.held_casts, HeldCast(name, seconds, hits)),
            attributed_followups=True,
            recorded_order=tuple(sorted((*w.recorded_order, (name, seconds)), key=lambda row: row[1])),
            recorded_timings=(*w.recorded_timings, ActionTiming(name, seconds,
                tuple(sorted((h['timestamp'] - start) / 1000 for h in packets.get(
                    (event.get('packetID'), event.get('abilityGameID')), ()))))),
            comparison_notes=tuple(dict.fromkeys((*w.comparison_notes,
                'Held follow-ups count toward the burst that granted them.'))),
            actual_package_potency=None, best_package_potency=None)
        if recipient is not None:
            w = windows[recipient]
            borrowed = next((entry for entry in w.proposed_order if entry[0] == name), None)
            windows[recipient] = replace(w,
                carried_casts=(*w.carried_casts, HeldCast(name, seconds, hits)),
                actions=tuple(replace(a, casts=max(0, a.casts - 1), hits=max(0, a.hits - hits),
                    expected=max(0, a.expected - 1) if a.expected is not None else None)
                    if a.name == name else a for a in w.actions),
                recorded_order=tuple(row for row in w.recorded_order if row != (name, seconds)),
                recorded_timings=tuple(t for t in w.recorded_timings
                    if (t.name, t.cast_seconds) != (name, seconds)),
                proposed_order=tuple(row for row in w.proposed_order if row != borrowed),
                proposed_timings=tuple(t for t in w.proposed_timings
                    if (t.name, t.cast_seconds) != borrowed),
                attributed_followups=True,
                comparison_notes=tuple(dict.fromkeys((*w.comparison_notes,
                    'The carried follow-up counts toward its original burst.'))),
                actual_package_potency=None, best_package_potency=None)
    return tuple(windows)


def rescore_receiving_windows(windows, casts, damage, buffs, life, combatants, names,
                             actions, source, start, end, targetable, spell_potencies,
                             primary_hits, periodic_target_windows):
    """Keep incoming follow-ups fixed while scoring only the receiving burst's grants."""
    from ..package_analysis import summarize_packages
    from .package_resources import requiescat_model
    from .package_rules import RULES

    packet_values = {key: value for key, value in spell_potencies.items() if value is not None}
    resource_model = requiescat_model(casts, buffs, life, combatants, names, actions, source, start, end)
    output = []
    for window in windows:
        if not window.carried_casts or window.held_casts:
            output.append(window)
            continue
        incoming = {(c.name, c.cast_seconds) for c in window.carried_casts}
        fixed = {(e.get('packetID'), e.get('abilityGameID')) for e in casts
                 if e.get('sourceID') == source and e.get('type') == 'cast'
                 and (_event_name(e, names), (e['timestamp'] - start) / 1000) in incoming}
        begin, finish = start + window.start_seconds * 1000, start + window.end_seconds * 1000
        scored, = summarize_packages(casts, damage, buffs, life, names, actions,
            source, start, end, ((begin, finish),), targetable, RULES,
            packet_values=packet_values, primary_hits=primary_hits, resource_model=resource_model,
            periodic_target_windows=periodic_target_windows, fixed_casts=fixed)
        by_name = {a.name: a for a in scored.actions}
        timings = tuple(ActionTiming(name, seconds, tuple(sorted({
            (h['timestamp'] - start) / 1000 for h in damage
            if h.get('sourceID') == source and h.get('type') == 'damage'
            and not h.get('tick') and h.get('amount', 0) > 0
            and (h.get('packetID'), h.get('abilityGameID')) in fixed
            and _event_name(h, names) == name}))) for name, seconds in incoming)
        output.append(replace(window, attributed_followups=False,
            comparison_notes=tuple(note for note in window.comparison_notes
                if note != 'The carried follow-up counts toward its original burst.'),
            actions=tuple(replace(a, expected=by_name[a.name].expected) for a in window.actions),
            actual_package_potency=scored.actual_package_potency,
            best_package_potency=scored.best_package_potency,
            recorded_order=tuple(sorted((*window.recorded_order, *incoming), key=lambda r: r[1])),
            recorded_timings=(*window.recorded_timings, *timings),
            proposed_order=tuple(sorted((*scored.proposed_order, *incoming), key=lambda r: r[1]))
                if scored.proposed_order else (),
            proposed_timings=(*scored.proposed_timings, *timings)))
    return tuple(output)
