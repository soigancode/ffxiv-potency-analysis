"""Requiescat charges follow the proposed casts, rather than recorded removal."""

import re
from dataclasses import replace

from ..burst_opportunities import PotencyResource
from ..events import _event_name
from .state import BLADES, HOLY, REQUIESCAT, replay_spells


def requiescat_model(casts, buffs, life, combatants, names, actions, source, start, end):
    """Keep out-of-package spells fixed, including Divine Might's priority."""
    own = sorted((e for e in casts if e.get('sourceID') == source
                  and e.get('type') == 'cast' and not e.get('fake')),
                 key=lambda e: e['timestamp'])
    own = list({(e.get('packetID', e['timestamp']), e.get('abilityGameID')): e
                for e in own}.values())
    grants = [e for e in buffs if e.get('targetID') == source
              and e.get('abilityGameID') == REQUIESCAT
              and e.get('type') in {'applybuff', 'refreshbuff'}]
    description = ' '.join(actions.get('Imperator', {}).get('description', ()))
    count_match = re.search(r'Grants (\d+) stacks of Requiescat', description)
    duration_match = re.search(r'Grants \d+ stacks of Requiescat Duration: (\d+)s', description)
    count = int(count_match[1]) if count_match else 4
    duration = int(duration_match[1]) * 1000 if duration_match else 30000
    recorded = replay_spells(casts, buffs, life, combatants, names, source, start, end)
    divine = {(s.packet, s.ability_id) for s in recorded.spells if s.enhancement == 'Divine Might'}

    def configure(candidates, labels, begin, finish, scope):
        previous = replay_spells([e for e in casts if e['timestamp'] < begin],
            [e for e in buffs if e['timestamp'] < begin],
            [e for e in life if e['timestamp'] < begin], combatants, names, source, start, begin)
        remaining = next(r.remaining for r in previous.ready if r.name == 'Requiescat charges')
        initial = [a for c in combatants if c.get('sourceID') == source
                   for a in c.get('auras', ()) if a.get('ability') == REQUIESCAT]
        expiry = start + initial[0].get('duration', duration) if initial else start
        preceding = [e for e in grants if e['timestamp'] < begin]
        if preceding:
            last = max(preceding, key=lambda e: e['timestamp'])
            expiry = last['timestamp'] + last.get('duration', duration)
        events = []
        for grant in grants:
            if not begin <= grant['timestamp'] < finish:
                continue
            # A selected Imperator supplies its own grant at its proposed time.
            generator = next((e for e in own if _event_name(e, names) == 'Imperator'
                and begin <= e['timestamp'] < finish
                and (grant.get('packetID') is not None
                     and e.get('packetID') == grant.get('packetID')
                     or abs(e['timestamp'] - grant['timestamp']) <= 1)), None)
            if generator is None:
                events.append((grant['timestamp'], grant.get('stack', count), grant.get('duration', duration)))
        for event in own:
            name = _event_name(event, names)
            if (begin <= event['timestamp'] < finish and name not in scope
                    and name in HOLY | frozenset(BLADES) | {'Clemency'}
                    and (event.get('packetID'), event.get('abilityGameID')) not in divine):
                events.append((event['timestamp'], -1, 0))
        events.extend((e['timestamp'], 0, 0) for e in life if e.get('type') == 'death'
                      and e.get('targetID') == source and begin <= e['timestamp'] < finish)
        configured = []
        for candidate in candidates:
            name = labels[candidate.name]
            enhanced = (actions.get(name, {}).get('potency') or {}).get(
                'conditional_potencies', {}).get('Requiescat')
            if name == 'Imperator':
                candidate = replace(candidate, grants_resource='Requiescat',
                    resource_charges=count, resource_duration_ms=duration)
            elif enhanced is not None:
                candidate = replace(candidate, potency_resource='Requiescat', enhanced_potency=enhanced,
                    enhanced_potency_windows=tuple((a, b, p * enhanced / candidate.potency)
                        for a, b, p in candidate.potency_windows) if candidate.potency else ())
            configured.append(candidate)
        evidence = not (remaining and initial and not preceding
                        and not isinstance(initial[0].get('duration'), (int, float)))
        return tuple(configured), (PotencyResource('Requiescat', remaining, expiry,
                                                   tuple(sorted(events)), evidence),)

    return configure
