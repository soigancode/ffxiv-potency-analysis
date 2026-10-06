"""Confirm an opening personal buff when its activation cast is missing."""

from .buffs import damage_snapshot_times
from .events import _event_name, _has_buff


def opening_personal_buff(status, action, duration, casts, damage, buffs, combatants,
                         names, source, start, end, windows=()):
    """Use initial auras or snapshots before the first recorded status boundary.

    Only use this for personal effects that uniquely identify their activation.
    An observed activation at pull belongs to that cast, rather than pre-pull.
    """
    activations = [e["timestamp"] for e in casts if e.get("sourceID") == source
                   and not e.get("fake") and e.get("type", "cast") == "cast"
                   and _event_name(e, names) == action]
    if any(time <= start for time in activations):
        return False
    if any(a.get("ability") == status for c in combatants or ()
           if c.get("sourceID") == source for a in c.get("auras", ())):
        return True
    events = [e for e in buffs if e.get("targetID") == source
              and e.get("sourceID") in {source, None} and e.get("abilityGameID") == status
              and e.get("type") in {"applybuff", "refreshbuff", "removebuff"}]
    before = sorted((e for e in events if e["timestamp"] <= start),
                    key=lambda e: e["timestamp"])
    if before:
        latest = before[-1]
        return (latest["type"] in {"applybuff", "refreshbuff"}
                and latest["timestamp"] < start < latest["timestamp"] + duration)
    if any(begin < start < finish for begin, finish, _ in windows):
        return True
    boundary = min([end, *activations, *(e["timestamp"] for e in events)])
    snapshots = damage_snapshot_times(damage, casts)
    return any(
        e.get("sourceID") == source and not e.get("tick") and e.get("amount", 0) > 0
        and e["timestamp"] >= start
        and _has_buff(e, status)
        and start - duration < snapshots.get((e.get("packetID"), e.get("abilityGameID")),
                                            e["timestamp"]) < min(boundary, start + duration)
        for e in damage
    )
