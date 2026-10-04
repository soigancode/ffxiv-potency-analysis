"""Fight or Flight opportunities from Paladin grants and patch-specific actions."""

import re
from collections import Counter

from ..burst_opportunities import (
    BurstAction,
    BurstWindow,
    GrantedAction,
    cooldown_opportunities,
    granted_package,
    next_slot,
)
from ..cooldown_timing import living_windows
from ..events import _event_name
from .buffs import FIGHT_OR_FLIGHT
from .state import BLADES

BURST_ACTIONS = (
    "Imperator", "Goring Blade", *BLADES, "Blade of Honor",
    "Circle of Scorn", "Expiacion", "Intervene",
)
GRANTS = {"Goring Blade": 1003847, "Confiteor": 1003019, "Blade of Honor": 1003831}


def _grant(action, buffs, casts, names, begin, finish, life, source):
    status = GRANTS[action]
    grants = [e for e in buffs if e.get("abilityGameID") == status
              and e.get("targetID") == source and e.get("sourceID") in {source, None}
              and e.get("type") in {"applybuff", "refreshbuff"} and e["timestamp"] < finish]
    for event in sorted(grants, key=lambda e: e["timestamp"], reverse=True):
        time = event["timestamp"]
        duration = event.get("duration")
        if not isinstance(duration, (float, int)):
            continue
        deadline = time + duration
        # A consumed or removed opening grant is not available to move again.
        if any(time <= c["timestamp"] < begin and _event_name(c, names) == action for c in casts):
            continue
        if any(time < e["timestamp"] < begin and e.get("abilityGameID") == status
               and e.get("targetID") == source and e.get("type") == "removebuff" for e in buffs):
            continue
        death = next((e["timestamp"] for e in sorted(life, key=lambda e: e["timestamp"])
                      if e.get("type") == "death" and e.get("targetID") == source
                      and e["timestamp"] >= time), None)
        if death is not None:
            deadline = min(deadline, death)
        if max(begin, time) < min(finish, deadline):
            return max(begin, time), min(finish, deadline)
    return None


def summarize_burst_opportunities(casts, buffs, life, names, actions, source, start, end,
                                  buff_windows, targetable, damage, potency_rows):
    """Use local, conservative opportunities rather than a fixed ideal rotation.

    Recorded grants establish the spell package. Combo dependencies and GCD
    durations come from reference actions. Cooldown additions preserve all
    recorded uses, including outside cleaves, so they cannot cost future uses.
    Missing opening, targetability or resource evidence remains unknown.
    """
    own = []
    seen = set()
    for event in casts:
        key = (event.get("packetID"), event.get("abilityGameID"))
        if key[0] is None:
            key = (event["timestamp"], event.get("abilityGameID"))
        if (event.get("type") == "cast" and event.get("sourceID") == source
                and not event.get("fake") and key not in seen):
            own.append(event)
            seen.add(key)
    own.sort(key=lambda e: e["timestamp"])
    known_targets = targetable is not None and (
        bool(targetable.intervals) or targetable.seconds == 0)
    living = (
        living_windows(targetable.intervals, life, source, start, end)
        if targetable is not None and known_targets else ()
    )
    result = []
    for begin, finish, strength in buff_windows.get(FIGHT_OR_FLIGHT, ()):
        begin, finish = max(start, begin), min(end, finish)
        if finish <= begin:
            continue
        cycle_end = min((a for a, _, _ in buff_windows.get(FIGHT_OR_FLIGHT, ())
                         if a >= finish), default=end)
        within = [e for e in own if begin <= e["timestamp"] < finish]
        counts = Counter(_event_name(e, names) for e in within)
        packets = {(e.get("packetID"), e.get("abilityGameID")) for e in within
                   if e.get("packetID") is not None}
        hits = Counter(_event_name(e, names) for e in damage or ()
                       if e.get("type") == "damage" and e.get("sourceID") == source
                       and e.get("amount", 0) > 0 and not e.get("tick")
                       and (e.get("packetID"), e.get("abilityGameID")) in packets)
        packet_hits = Counter((e.get("packetID"), e.get("abilityGameID")) for e in damage or ()
                              if e.get("type") == "damage" and e.get("sourceID") == source
                              and e.get("amount", 0) > 0 and not e.get("tick")
                              and e.get("packetID") is not None)
        grants = {name: _grant(name, buffs, own, names, begin, finish, life, source)
                  for name in GRANTS}
        package = []
        root = grants["Confiteor"]
        for name in ("Goring Blade", *BLADES):
            grant = grants["Goring Blade"] if name == "Goring Blade" else root
            data = actions.get(name, {})
            recast = data.get("recast_seconds")
            potency = data.get("potency") or {}
            if grant is None or not isinstance(recast, (int, float)) or recast <= 0:
                continue
            combo = next((line.removeprefix("Combo Action: ") for line in data.get("description", ())
                          if line.startswith("Combo Action: ")), None)
            # Enhanced values apply only when the recorded Requiescat grant is
            # still active. No resource-generating casts are invented.
            enhanced = any(e.get("abilityGameID") == 1001368
                           and e.get("targetID") == source
                           and e.get("sourceID") in {source, None}
                           and e.get("type") in {"applybuff", "refreshbuff"}
                           and e["timestamp"] <= grant[0]
                           and e["timestamp"] + e.get("duration", 0) >= grant[1]
                           for e in buffs)
            value = potency.get("conditional_potencies", {}).get("Requiescat", potency.get("base", 0)) \
                if enhanced else potency.get("base", 0)
            package.append(GrantedAction(name, *grant, recast * 1000, value, combo))
        previous_gcd = next((e for e in reversed(own) if e["timestamp"] < begin
                             and actions.get(_event_name(e, names), {}).get("type", "").casefold()
                             in {"spell", "weaponskill"}), None)
        gcd_start = begin
        if previous_gcd is not None:
            recast = actions[_event_name(previous_gcd, names)].get("recast_seconds")
            if isinstance(recast, (int, float)):
                gcd_start = max(begin, previous_gcd["timestamp"] + recast * 1000)
        plan = granted_package(tuple(package), living, gcd_start, finish) if known_targets else ()
        planned = set(plan)
        unlocks = {}
        time = gcd_start
        for name in plan:
            action = next(a for a in package if a.name == name)
            slot = next_slot(max(time, action.available), living, min(finish, action.deadline))
            if slot is None:
                continue
            for consumer in GRANTS:
                if f"Additional Effect: Grants {consumer} Ready" in actions[name].get("description", ()):
                    unlocks[consumer] = slot + 700
            time = slot + action.recast_ms
        rows = []
        retained = set()
        for name in BURST_ACTIONS:
            actual = counts[name]
            expected = None
            notes = []
            if known_targets and name in {"Goring Blade", *BLADES}:
                if any(a.name == name for a in package):
                    expected = max(actual, int(name in planned))
                elif actual:
                    expected = actual
            elif known_targets and name == "Blade of Honor":
                grant = grants[name]
                if grant is not None:
                    expected = max(actual, int(next_slot(grant[0], living, grant[1]) is not None))
                elif name in unlocks:
                    expected = max(actual, int(next_slot(unlocks[name], living, finish) is not None))
                elif actual:
                    expected = actual
            elif known_targets and name not in {"Goring Blade", *BLADES, "Blade of Honor"}:
                data = actions.get(name, {})
                recast = data.get("recast_seconds")
                match = re.search(r"Maximum Charges: (\d+)", " ".join(data.get("description", ())))
                if isinstance(recast, (int, float)) and recast > 0:
                    times = tuple(float(e["timestamp"]) for e in own if _event_name(e, names) == name)
                    expected = cooldown_opportunities(times, recast * 1000,
                        int(match[1]) if match else 1, begin, finish, living)
            if expected is None:
                notes.append("availability unconfirmed")
            elif expected > actual and name in {"Goring Blade", *BLADES, "Blade of Honor"}:
                dependency = next((line.removeprefix("Combo Action: ")
                                   for line in actions.get(name, {}).get("description", ())
                                   if line.startswith("Combo Action: ")), None)
                inherited = dependency in retained or (
                    grants.get(name) is None and any(
                        f"Additional Effect: Grants {name} Ready" in actions.get(parent, {}).get("description", ())
                        for parent in retained))
                outside_cleave = any(
                    _event_name(e, names) == name and not begin <= e["timestamp"] < finish
                    and begin <= e["timestamp"] < cycle_end
                    and packet_hits[(e.get("packetID"), e.get("abilityGameID"))] > 1
                    for e in own)
                if outside_cleave or inherited:
                    expected = None
                    retained.add(name)
                    notes.append("outside multi-target use retained")
            rows.append(BurstAction(name, actual, hits[name], expected, tuple(notes)))
        # These rows retain potion, enhancement and penalty modifiers. Only
        # the personal buff removed by the alignment calculation is restored.
        potency = sum(value * strength for time, _, value, buffed in potency_rows
                      if buffed and begin <= time < finish)
        result.append(BurstWindow((begin - start) / 1000, (finish - start) / 1000,
                                  tuple(rows), potency))
    return tuple(result)
