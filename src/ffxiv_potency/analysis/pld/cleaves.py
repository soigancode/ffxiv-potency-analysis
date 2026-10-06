"""Compare recorded held follow-ups with their feasible earlier single-target uses."""

import re
from dataclasses import replace

from ..burst_opportunities import HeldCleave
from ..events import _event_name
from ..penalties import penalty_multiplier, revival_multiplier
from .buffs import FIGHT_OR_FLIGHT
from .state import BLADES


def compare_held_cleaves(windows, casts, damage, potency_rows, names, actions, source,
                        start, spell_potencies, self_windows, buffs, debuffs, combatants,
                        profile, penalty_rules):
    own = sorted((e for e in casts if e.get('sourceID') == source
        and e.get('type') == 'cast' and not e.get('fake')), key=lambda e: e['timestamp'])
    packets = {}
    for hit in damage:
        if (hit.get('sourceID') == source and hit.get('type') == 'damage'
                and not hit.get('tick') and hit.get('amount', 0) > 0):
            packets.setdefault((hit.get('packetID'), hit.get('abilityGameID')), []).append(hit)
    values = {}
    for event, _, _, value in potency_rows:
        if not event.get('tick'):
            key = event.get('packetID'), event.get('abilityGameID')
            values[key] = values.get(key, 0) + value
    initial = {a['ability']: start + a['duration'] if isinstance(a.get('duration'), (int, float)) else float('inf')
               for c in combatants if c.get('sourceID') == source
               for a in c.get('auras', ()) if 'ability' in a}
    statuses = sorted((e for e in (*buffs, *debuffs) if e.get('targetID') == source),
                      key=lambda e: e['timestamp'])

    def earlier_modifier(time):
        expiry = dict(initial)
        for event in statuses:
            if event['timestamp'] > time:
                break
            status = event.get('abilityGameID')
            if event.get('type') in {'applybuff', 'refreshbuff', 'applydebuff', 'refreshdebuff'}:
                duration = event.get('duration')
                expiry[status] = (event['timestamp'] + duration if isinstance(duration, (int, float))
                                  else float('inf'))
            elif event.get('type') in {'removebuff', 'removedebuff'}:
                expiry.pop(status, None)
        active = {s for s, deadline in expiry.items() if time < deadline}
        evidence = {'buffs': '.'.join(str(s) for s in active)}
        factor = penalty_multiplier(evidence, penalty_rules) * revival_multiplier(evidence, profile)
        if profile.potion_buff_id in active:
            factor *= profile.player_potion_multiplier
        for intervals in self_windows.values():
            factor *= next((strength for a, b, strength in intervals if a <= time < b), 1)
        return factor

    result = []
    for window in windows:
        begin, finish = start + window.start_seconds * 1000, start + window.end_seconds * 1000
        root = next((e for e in own if begin <= e['timestamp'] < finish
                     and _event_name(e, names) == BLADES[0]), None)
        if root is None:
            result.append(window)
            continue
        next_root = min((e['timestamp'] for e in own if e['timestamp'] > root['timestamp']
                         and _event_name(e, names) == BLADES[0]), default=float('inf'))
        chain = {}
        previous = root['timestamp']
        for name in BLADES[1:]:
            event = next((e for e in own if previous < e['timestamp'] < next_root
                          and _event_name(e, names) == name), None)
            if event is None:
                break
            chain[name] = event
            previous = event['timestamp']
        valor = chain.get('Blade of Valor')
        if valor is not None:
            # Honor Ready belongs to this Valor until the next Valor grants it
            # again. A later Fight or Flight does not change grant ownership.
            next_valor = min((e['timestamp'] for e in own if e['timestamp'] > valor['timestamp']
                             and _event_name(e, names) == 'Blade of Valor'), default=float('inf'))
            grant = next((e for e in buffs if e.get('abilityGameID') == 1003831
                and e.get('targetID') == source and e.get('type') in {'applybuff', 'refreshbuff'}
                and valor['timestamp'] <= e['timestamp'] < valor['timestamp'] + 1500), None)
            expiry = (grant['timestamp'] + grant['duration']
                      if grant is not None and isinstance(grant.get('duration'), (int, float)) else previous)
            honor = next((e for e in own if valor['timestamp'] < e['timestamp'] < min(next_valor, expiry)
                          and _event_name(e, names) == 'Blade of Honor'), None)
            if honor is not None:
                chain['Blade of Honor'] = honor
        comparisons = []
        proposed = dict(window.proposed_order)
        for name, event in chain.items():
            if begin <= event['timestamp'] < finish or name not in proposed:
                continue
            key = event.get('packetID'), event.get('abilityGameID')
            landed = packets.get(key, ())
            targets = {(h.get('targetID'), h.get('targetInstance', 1)) for h in landed}
            if len(targets) < 2 or key not in values:
                continue
            earlier = start + proposed[name] * 1000
            spec = actions.get(name, {}).get('potency') or {}
            base = spec.get('base')
            if not isinstance(base, (int, float)):
                continue
            enhancement = 'None'
            if name in BLADES:
                imperator = proposed.get('Imperator')
                duration = re.search(r'Grants \d+ stacks of Requiescat Duration: (\d+)s',
                    ' '.join(actions.get('Imperator', {}).get('description', ())))
                if imperator is None or duration is None or not 0 <= proposed[name] - imperator < int(duration[1]):
                    continue
                if any(start + imperator * 1000 <= c['timestamp'] <= earlier
                       and _event_name(c, names) in {'Holy Spirit', 'Holy Circle', 'Clemency'} for c in own):
                    continue
                base = spec.get('conditional_potencies', {}).get('Requiescat', base)
                enhancement = ('Requiescat' if spell_potencies.get(key) is not None else 'None')
            recorded_buffs = {int(s) for h in landed for s in str(h.get('buffs', '')).split('.') if s.isdigit()}
            effects = tuple(label for status, label in ((FIGHT_OR_FLIGHT, 'Fight or Flight'),
                (profile.potion_buff_id, 'potion')) if status in recorded_buffs)
            comparisons.append(HeldCleave(name, (event['timestamp'] - start) / 1000,
                proposed[name], len(targets), values[key], base * earlier_modifier(earlier), enhancement, effects))
        held_names = ({c.name for c in comparisons}
                      if comparisons and sum(c.held_potency - c.earlier_potency for c in comparisons) >= 0 else set())
        result.append(replace(window, held_cleaves=tuple(comparisons),
            inside_package_potency=window.best_package_potency,
            actions=tuple(replace(a, expected=a.package_casts) if a.name in held_names else a
                          for a in window.actions),
            actual_package_potency=None if comparisons else window.actual_package_potency,
            best_package_potency=None if comparisons else window.best_package_potency,
            comparison_notes=(*window.comparison_notes,
                'Held follow-ups cross burst windows. See their action tooltips.') if comparisons
                else window.comparison_notes))
    return tuple(result)
