"""Potion placement against recorded Fight or Flight sequences."""

from dataclasses import replace

from ..events import _event_name, _has_buff
from ..potion_alignment import PotionAlignment
from .buffs import FIGHT_OR_FLIGHT


def annotate_potion_alignment(window, casts, damage, names, source, start, end,
                             fof_windows, potion_buff_id, buffs=(), life=(),
                             potency_rows=(), potion_multiplier=None):
    """Keep completion unchanged and flag actions from the associated burst.

    Independent cooldowns belong to a burst only when used during its recorded
    buff. Spell follow-ups remain attached to their Imperator/Requiescat use,
    even when delayed beyond Fight or Flight. Recorded potion snapshots take
    precedence over small differences between cast and buff timestamps.
    """
    begin = start + window.start_seconds * 1000
    finish = start + window.end_seconds * 1000
    seen = set()
    own = []
    for event in sorted(casts, key=lambda e: e['timestamp']):
        packet = event.get('packetID')
        key = packet if packet is not None else event['timestamp'], event.get('abilityGameID')
        if event.get('sourceID') == source and key not in seen:
            seen.add(key)
            own.append(event)
    snapshots = PotionAlignment(damage, source, potion_buff_id, begin, finish,
                                potency_rows, potion_multiplier)
    inside = snapshots.inside

    chain = {'Confiteor', 'Blade of Faith', 'Blade of Truth', 'Blade of Valor', 'Blade of Honor'}
    scope = {a.name for a in window.actions}
    triggers = [e for e in own if _event_name(e, names) in {'Imperator', 'Requiescat'}]
    choices = []
    for buff_start, buff_end, *_ in fof_windows:
        tracked = [e for e in own if buff_start <= e['timestamp'] < buff_end
                   and _event_name(e, names) in scope]
        grants = [e for e in buffs if e.get('targetID') == source
                  and e.get('abilityGameID') == 1003847
                  and e.get('type') in {'applybuff', 'refreshbuff'}
                  and buff_start <= e['timestamp'] < buff_end
                  and isinstance(e.get('duration'), (int, float))]
        for event in own:
            if _event_name(event, names) != 'Goring Blade' or event['timestamp'] < buff_end:
                continue
            if any(g['timestamp'] <= event['timestamp'] < g['timestamp'] + g['duration']
                   and not any(e.get('targetID') == source and e.get('type') == 'death'
                               and g['timestamp'] <= e['timestamp'] <= event['timestamp']
                               for e in life) for g in grants):
                tracked.append(event)
        for index, trigger in enumerate(triggers):
            if not buff_start <= trigger['timestamp'] < buff_end:
                continue
            sequence_end = triggers[index + 1]['timestamp'] if index + 1 < len(triggers) else end
            tracked.extend(e for e in own if buff_end <= e['timestamp'] < sequence_end
                           and _event_name(e, names) in chain)
        count = sum(inside(e) for e in tracked)
        if count or max(begin, buff_start) < min(finish, buff_end):
            choices.append((count, max(0, min(finish, buff_end) - max(begin, buff_start)),
                            buff_start, buff_end, tracked))
    if not choices:
        return window
    _, _, buff_start, buff_end, tracked = max(choices, key=lambda choice: choice[:3])
    notes = {}
    before = []
    after = []
    for name in (a.name for a in window.actions):
        for side, boundary in (('before', begin), ('after', finish)):
            outside = [e for e in tracked if _event_name(e, names) == name
                       and snapshots.outside(e) and snapshots.side(e) == side]
            if not outside:
                continue
            offsets = ', '.join(f"{abs(e['timestamp'] - boundary) / 1000:.1f}s" for e in outside)
            if any(begin <= e['timestamp'] < finish for e in outside):
                note = f"{len(outside)} {name} had landed damage without a potion snapshot."
            else:
                note = (f"{len(outside)} {name} used {side} the potion "
                        f"({offsets} {side} its {'start' if side == 'before' else 'end'}).")
            note += snapshots.gain_note(outside)
            notes.setdefault(name, []).append(note)
            (before if side == 'before' else after).append(note)
    # Filler GCDs and auto-attacks are absent from burst-table columns, but
    # their snapshots still decide whether the buff/potion overlap lost damage.
    tracked_keys = {(e.get('packetID'), e.get('abilityGameID')) for e in tracked}
    own_packets = {(e.get('packetID'), e.get('abilityGameID')): e for e in own}
    snapshot_times = {(h.get('packetID'), h.get('abilityGameID')): time
                      for h, time, _, _ in potency_rows if not h.get('tick')}
    other_hits = {'before': [], 'after': []}
    for key in snapshots.unpotted - tracked_keys:
        hits = [h for h in snapshots.hits[key] if not _has_buff(h, potion_buff_id)
                and _has_buff(h, FIGHT_OR_FLIGHT)]
        if not hits:
            continue
        event = own_packets.get(key, {**hits[0], 'timestamp': snapshot_times.get(key, hits[0]['timestamp'])})
        if not buff_start <= event['timestamp'] < buff_end:
            continue
        other_hits[snapshots.side(event)].append((event, len(hits)))
    for side, entries in other_hits.items():
        if not entries:
            continue
        count = sum(n for _, n in entries)
        text = (f"{count} other landed {'hit' if count == 1 else 'hits'} during Fight or Flight "
                "lacked a potion snapshot.")
        text += snapshots.gain_note([event for event, _ in entries])
        (before if side == 'before' else after).append(text)
    timing = []
    if before and buff_start < begin:
        timing.append(f"Fight or Flight started {(begin - buff_start) / 1000:.1f}s before the potion.")
    if after and buff_end > finish:
        timing.append(f"Fight or Flight ended {(buff_end - finish) / 1000:.1f}s after the potion.")
    return replace(window, actions=tuple(replace(a, notes=a.notes + tuple(notes.get(a.name, ())),
                                                 review=a.review or a.name in notes)
                                         for a in window.actions),
                   alignment_notes=tuple(before + after + timing),
                   before_window_notes=tuple(before + (timing[:1] if before and buff_start < begin else [])),
                   after_window_notes=tuple(after + (timing[-1:] if after and buff_end > finish else [])))
