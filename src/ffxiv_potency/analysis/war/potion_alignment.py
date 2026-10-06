"""Recorded potion placement relative to WAR burst sequences, without rescheduling."""

import re
from dataclasses import replace

from ..events import _event_name
from ..potion_alignment import PotionAlignment
from .buffs import INNER_RELEASE
from .bursts import _own_casts, _spender_casts


def annotate_potion_alignment(window, casts, buffs, names, actions, source, start, end,
                             cast_packets=(), life=(), *, damage=(), potion_id=1000049,
                             potency_rows=(), potion_multiplier=None):
    """Flag related burst actions outside the potion independently of completion.

    Select the IR sequence with the most potted free spenders, preferring an
    activation inside the potion on ties. This avoids labelling a prior burst's
    deliberately held Ruination as the current burst's missing spenders.
    Counts and optimized packages are unchanged: moving the potion is not solved.
    """
    begin = start + window.start_seconds * 1000
    finish = start + window.end_seconds * 1000
    own = _own_casts(casts, source)
    triggers = [e['timestamp'] for e in own if _event_name(e, names) == 'Inner Release']
    packets = dict(cast_packets)
    snapshots = PotionAlignment(damage, source, potion_id, begin, finish,
                                potency_rows, potion_multiplier)

    def inside(event, label):
        return snapshots.inside(event,
            (event.get('packetID'), event.get('abilityGameID')) in packets.get(label, ()))

    choices = []
    for index, activation in enumerate(triggers):
        sequence_end = triggers[index + 1] if index + 1 < len(triggers) else end
        sequence = [(e, _event_name(e, names)) for e in own
                    if activation <= e['timestamp'] < sequence_end]
        spenders = _spender_casts(sequence, buffs, source, activation, sequence_end)
        tracked = {'IR spenders': spenders}
        for name in ('Primal Rend', 'Primal Ruination', 'Primal Wrath'):
            tracked[name] = [e for e, action in sequence if action == name]
        active = any(e.get('targetID') == source and e.get('abilityGameID') == INNER_RELEASE
                     and e.get('type') in {'applybuff', 'refreshbuff'}
                     and activation <= e['timestamp'] <= activation + 1000
                     and isinstance(e.get('duration'), (int, float))
                     and e['timestamp'] <= begin < e['timestamp'] + e['duration'] for e in buffs)
        within_count = sum(inside(e, label) for label, events in tracked.items() for e in events)
        if not (within_count or active or begin <= activation < finish):
            continue
        score = (sum(inside(e, 'IR spenders') for e in spenders),
                 begin <= activation < finish, within_count, activation)
        choices.append((score, activation, tracked))
    notes = {}
    overview = []
    before_notes = []
    after_notes = []
    if choices:
        _, activation, tracked = max(choices, key=lambda choice: choice[0])
        for label, events in tracked.items():
            for side in ('before', 'after'):
                outside = [e for e in events if snapshots.outside(e,
                    (e.get('packetID'), e.get('abilityGameID')) in packets.get(label, ()))
                    and snapshots.side(e) == side]
                if not outside:
                    continue
                offsets = ', '.join(f"{abs(e['timestamp'] - (begin if side == 'before' else finish)) / 1000:.1f}s"
                                    for e in outside)
                action = 'IR spender' if label == 'IR spenders' and len(outside) == 1 else label
                note = (f"{len(outside)} {action} from the associated Inner Release sequence "
                        f"{'was' if len(outside) == 1 else 'were'} used {side} this potion "
                        f"({offsets} {side} its {'start' if side == 'before' else 'end'}).")
                if any(begin <= e['timestamp'] < finish for e in outside):
                    note = f"{len(outside)} {action} had landed damage without a potion snapshot."
                note += snapshots.gain_note(outside)
                notes.setdefault(label, []).append(note)
                timing = (f"{len(outside)} {action} used {side} the potion ({offsets} "
                          f"{side} its {'start' if side == 'before' else 'end'}).")
                if any(begin <= e['timestamp'] < finish for e in outside):
                    timing = note
                (before_notes if side == 'before' else after_notes).append(timing)
                overview.append(timing)
        description = ' '.join(actions.get('Inner Release', {}).get('description', ()))
        stacks = re.search(r'Grants (\d+) stacks of Inner Release', description)
        gcd = actions.get('Fell Cleave', {}).get('recast_seconds')
        inside_spenders = sum(inside(e, 'IR spenders') for e in tracked['IR spenders'])
        if (stacks is not None and isinstance(gcd, (int, float)) and gcd > 0
                and begin + gcd * 1000 < activation < finish
                and inside_spenders < int(stacks[1])
                and (not snapshots.available or any(snapshots.outside(e,
                    (e.get('packetID'), e.get('abilityGameID')) in packets.get('IR spenders', ()))
                    for e in tracked['IR spenders']))):
            note = (f"Inner Release was activated {(activation - begin) / 1000:.1f}s into this "
                    f"potion, leaving {(finish - activation) / 1000:.1f}s before its end. "
                    "Not all IR spenders fit inside this potion. Check an earlier potion start.")
            notes.setdefault('IR spenders', []).append(note)
            overview.append(f"IR activated {(activation - begin) / 1000:.1f}s into the potion, "
                            f"leaving {(finish - activation) / 1000:.1f}s for its sequence.")
    # A consumed NC grant whose recorded lifetime extends into the potion is
    # evidence of early spending. It cannot be carried through death or renewal.
    consumers = [e for e in own if _event_name(e, names) in {'Inner Chaos', 'Chaotic Cyclone'}
                 and e['timestamp'] < begin and snapshots.outside(e,
                    (e.get('packetID'), e.get('abilityGameID')) in packets.get('Nascent Chaos', ()))]
    for event in consumers[-1:]:
        grants = [e for e in buffs if e.get('targetID') == source
                  and e.get('abilityGameID') == 1001897
                  and e.get('type') in {'applybuff', 'refreshbuff'}
                  and isinstance(e.get('duration'), (int, float))
                  and e['timestamp'] <= event['timestamp'] < begin < e['timestamp'] + e['duration']]
        unavailable = any(e.get('targetID') == source and e.get('type') == 'death'
                          and event['timestamp'] <= e['timestamp'] < begin for e in life)
        renewed = any(e.get('targetID') == source and e.get('abilityGameID') == 1001897
                      and e.get('type') in {'applybuff', 'refreshbuff'}
                      and event['timestamp'] < e['timestamp'] < begin for e in buffs)
        if grants and not unavailable and not renewed:
            note = (f"{_event_name(event, names)} was used {(begin - event['timestamp']) / 1000:.1f}s "
                    "before this potion. Its Nascent Chaos grant had time remaining at potion start. "
                    "Check whether the grant could have been saved for the potion.")
            note += snapshots.gain_note((event,))
            notes.setdefault('Nascent Chaos', []).append(note)
            timing = (f"{_event_name(event, names)} used {(begin - event['timestamp']) / 1000:.1f}s "
                      "before the potion while its grant could have lasted into the window.")
            before_notes.append(timing)
            overview.append(timing)
    return replace(window, actions=tuple(replace(a, notes=a.notes + tuple(notes.get(a.name, ())),
                                                 review=a.review or a.name in notes)
                                         for a in window.actions),
                   alignment_notes=tuple(overview), before_window_notes=tuple(before_notes),
                   after_window_notes=tuple(after_notes))
