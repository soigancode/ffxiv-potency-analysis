"""Carry other recorded abilities with their surrounding package GCDs."""

from dataclasses import replace

from .events import _event_name


def attach_weaves(candidates, labels, casts, names, actions, begin, finish, aliases=None,
                  excluded_anchors=(), fixed_names=(), fixed_casts=()):
    """Reserve the recorded first/second weave slot, allowing its GCD to move."""
    aliases = {} if aliases is None else aliases
    labels = dict(labels)
    by_name = {}
    for candidate in candidates:
        by_name.setdefault(labels[candidate.name], []).append(candidate)
    extra = [e for e in casts if begin <= e['timestamp'] < finish
             and actions.get(_event_name(e, names), {}).get('type', '').casefold() == 'ability'
             and (aliases.get(_event_name(e, names), _event_name(e, names)) not in by_name
                  or (e.get('packetID'), e.get('abilityGameID')) in fixed_casts)]
    offsets = {}
    fixed = []
    for event in extra:
        time = event['timestamp']
        if (_event_name(event, names) in fixed_names
                or (event.get('packetID'), event.get('abilityGameID')) in fixed_casts):
            # Resource activation times remain coupled to recorded grants
            # until their resource model can replay a moved activation.
            fixed.append(time)
            continue
        previous = [e for e in casts if e['timestamp'] < time
            and actions.get(_event_name(e, names), {}).get('type', '').casefold() in {'spell', 'weaponskill'}]
        if not previous:
            fixed.append(time)
            continue
        gcd = previous[-1]
        if (gcd['timestamp'] < begin
                or (gcd.get('packetID'), gcd.get('abilityGameID')) in excluded_anchors):
            fixed.append(time)
            continue
        name = _event_name(gcd, names)
        label = aliases.get(name, name)
        anchors = [c for c in by_name.get(label, ()) if c.gcd
                   and c.available <= gcd['timestamp'] < c.deadline]
        if not anchors:
            fixed.append(time)
            continue
        earliest = max(begin, min(c.available for c in anchors))
        ordinal = sum(earliest <= e['timestamp'] < gcd['timestamp']
            and (e.get('packetID'), e.get('abilityGameID')) not in excluded_anchors
            and aliases.get(_event_name(e, names), _event_name(e, names)) == label for e in casts)
        anchor = anchors[min(ordinal, len(anchors) - 1)]
        # Keep its first/second weave position relative to the preceding GCD.
        # Long gaps still use the closest weave slot rather than absolute time.
        position = min(2, max(1, round((time - gcd['timestamp']) / 700)))
        key = f'weave:{len(labels)}'
        labels[key] = _event_name(event, names)
        offsets.setdefault(anchor.name, []).append((key, position * 700))
    configured = []
    for candidate in candidates:
        slots = sorted(offsets.get(candidate.name, ()), key=lambda row: row[1])
        # Multiple recorded abilities cannot occupy the same proposed slot.
        occupied = 0
        ordered = []
        for key, offset in slots:
            occupied = max(offset, occupied + 700)
            ordered.append((key, occupied))
        configured.append(replace(candidate, weave_offsets=tuple(ordered)))
    return tuple(configured), labels, tuple(fixed)
