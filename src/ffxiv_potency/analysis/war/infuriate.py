"""Infuriate recharge evidence without inventing gauge or alternate rotations."""

import re
from dataclasses import dataclass

from ..events import _event_name
from .bursts import _own_casts
from .diagnostics import REDUCTIONS


@dataclass(frozen=True, slots=True)
class InfuriateTiming:
    opening_charges: int | None
    closing_charges: int | None
    next_charge_after_end: float | None
    opening_charges_minimum: int = 0


def infuriate_timing(casts, damage, names, actions, source, begin, finish, end):
    """Replay conservative opening charges, synchronizing when the cap is proven.

    Opening recharge is unknown. An earlier-than-bounded observed use
    reanchors the next recharge, as in shared cooldown timing. Reaching the
    charge cap synchronizes the timeline before reporting exact readiness.
    Reductions occur once per landed spender, including free IR spenders, and
    recharge pauses at the cap. Missing hits do not prove a reduction. Death
    does not reset cooldowns. This evaluates the recorded timeline only.
    """
    data = actions.get("Infuriate", {})
    recast = data.get("recast_seconds")
    match = re.search(r"Maximum Charges: (\d+)", " ".join(data.get("description", ())))
    if not isinstance(recast, (int, float)) or recast <= 0 or match is None:
        return InfuriateTiming(None, None, None)
    maximum = int(match[1])
    uses = [e["timestamp"] for e in _own_casts(casts, source)
            if _event_name(e, names) == "Infuriate" and e["timestamp"] < end]
    if not uses or uses[0] >= begin:
        return InfuriateTiming(None, None, None)
    recast *= 1000
    reduction, spenders = REDUCTIONS["Infuriate"]
    seen = set()
    events = [(t, 1) for t in uses[1:]]
    snapshots = {(e.get("packetID"), e.get("abilityGameID")): e["timestamp"]
                 for e in damage if e.get("sourceID") == source
                 and e.get("type") == "calculateddamage" and not e.get("tick")}
    for hit in sorted(damage, key=lambda e: e.get("timestamp", 0)):
        key = (hit.get("packetID"), hit.get("abilityGameID"))
        if (hit.get("sourceID") != source or hit.get("type") != "damage"
                or hit.get("tick") or hit.get("amount", 0) <= 0
                or _event_name(hit, names) not in spenders
                or not uses[0] <= hit["timestamp"] < end
                or hit.get("packetID") is None or key in seen):
            continue
        seen.add(key)
        # The snapshot is the server action time; the later damage event proves
        # the action landed, but travelling impacts must not delay its recharge.
        events.append((snapshots.get(key, hit["timestamp"]), 0))
    # Markers precede casts at their timestamp: potion ranges are [begin, end).
    events.extend(((begin, -2), (finish, -1), (end, 2)))
    available = 0
    ready = uses[0] + recast
    exact = False
    at_start = at_end = None
    opening_minimum = 0
    next_after_end = None
    for time, kind in sorted(events):
        while available < maximum and ready <= time:
            if exact and ready >= finish and next_after_end is None:
                next_after_end = (ready - finish) / 1000
            available += 1
            if available == maximum:
                exact = True
            ready += recast
        if kind == -2:
            at_start = available if exact else None
            opening_minimum = available
        elif kind == -1:
            at_end = available if exact else None
        elif kind == 0:
            if available < maximum:
                ready = max(time, ready - reduction)
                if ready == time:
                    if exact and time >= finish and next_after_end is None:
                        next_after_end = (time - finish) / 1000
                    available += 1
                    if available == maximum:
                        exact = True
                    ready += recast
        elif kind == 1:
            if available == maximum:
                ready = time + recast
            elif available == 0:
                # This observed cast proves an unmodelled charge. Retain a
                # conservative next-recharge bound instead of inventing one.
                ready = time + recast
                exact = False
            available = max(0, available - 1)
    return InfuriateTiming(at_start, at_end, next_after_end, opening_minimum)
