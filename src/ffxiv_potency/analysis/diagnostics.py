"""Shared report diagnostics driven by each job's recorded execution rules."""

import re
from dataclasses import replace
from importlib import import_module
from math import floor
from typing import Any

from .buffs import self_damage_multiplier
from .combos import infer_combos, summarize_combos
from .cooldown_timing import cooldown_timing, living_windows
from .diagnostic_types import (
    AlignmentWindow,
    BurstAlignment,
    FollowUpContext,
    OutsideAction,
)
from .events import _event_name, _has_buff

JOBS = {"warrior": "war", "bard": "brd", "machinist": "mch", "dancer": "dnc"}


def rules_for(job):
    return import_module(f".{JOBS[job]}.diagnostics", __package__)


def infer_job_combos(job, damage, actions, names, source, start, profile, food_missing,
                     guaranteed_packets, modifiers=None):
    if job not in {"warrior", "machinist", "dancer"}:
        return {}
    # Forced Crit/DH converts stats and rate buffs to damage. Such packets are
    # not interchangeable with ordinary same-target potency references.
    forced_ids = {id_ for id_, name in names.items()
                  if name in {"Inner Release", "Reassemble", "Reassembled"}}
    eligible = [e for e in damage if
                (e.get("packetID"), e.get("abilityGameID")) not in guaranteed_packets
                and not any(_has_buff(e, id_) for id_ in forced_ids)
                and "critical direct hit" not in " ".join(
                    actions.get(_event_name(e, names), {}).get("description", ())).lower()]
    return infer_combos(eligible, actions, names, source, start, profile, food_missing,
                        fixed=rules_for(job).FIXED, modifiers=modifiers)


def combo_summary(damage, casts, actions, names, source, inferences):
    gcds = []
    seen = set()
    for cast in casts:
        key = cast.get("packetID"), cast.get("abilityGameID")
        if (cast.get("sourceID") != source or cast.get("fake")
                or cast.get("type") != "cast" or key in seen
                or actions.get(_event_name(cast, names), {}).get("type", "").lower()
                not in {"weaponskill", "spell"}):
            continue
        if key[0] is not None:
            seen.add(key)
        gcds.append(cast)
    previous = {(e.get("packetID"), e.get("abilityGameID")): _event_name(gcds[i - 1], names)
                for i, e in enumerate(gcds) if i and e.get("packetID") is not None}
    inferred = {id(e): replace(inferences[id(e)], previous_gcd=previous.get(
        (e.get("packetID"), e.get("abilityGameID"))))
        for e in damage if id(e) in inferences}
    return summarize_combos(damage, actions, names, source, inferred)


def proc_damage(damage, inferences):
    """Propagate a consistent inferred combo packet into Dancer proc evidence.

    Conflicting AoE target fits do not establish the packet's combo state.
    Input events remain untouched; explicit fields always take precedence.
    """
    states = {}
    for event in damage:
        key = event.get("packetID"), event.get("abilityGameID")
        if key[0] is not None and id(event) in inferences:
            states.setdefault(key, set()).add(inferences[id(event)].comboed)
    return [dict(e, bonusPercent=int(next(iter(states[key]))))
            if len(states.get(key := (e.get("packetID"), e.get("abilityGameID")), ())) == 1
            and not isinstance(e.get("bonusPercent"), (int, float)) else e
            for e in damage]


def summarize_timing(job, casts, damage, actions, names, life, source, start, end, targetable):
    rules = rules_for(job)
    own = [e for e in casts if e.get("sourceID") == source and not e.get("fake")
           and e.get("type", "cast") == "cast"]
    living = living_windows(targetable.intervals, life, source, start, end)
    rows = []
    for name in rules.COOLDOWNS:
        action = actions.get(name, {})
        recast = 120 if name == "Radiant Finale" else action.get("recast_seconds")
        if not isinstance(recast, (int, float)) or recast <= 0:
            continue
        match = re.search(r"Maximum Charges: (\d+)", " ".join(action.get("description", ())))
        charges = int(match[1]) if match else 1
        consumers = getattr(rules, "COOLDOWN_GROUPS", {}).get(name, (name,))
        label = "/".join(consumers)
        times = tuple(float(e["timestamp"]) for e in own if _event_name(e, names) in consumers)
        reductions = []
        if name in rules.REDUCTIONS:
            amount, consumers = rules.REDUCTIONS[name]
            # Infuriate reductions require landed hits; Blazing Shot restores
            # tool recasts on execution, as in the existing maximum estimate.
            landed_packets = {(e.get("packetID"), e.get("abilityGameID")): float(e["timestamp"]) for e in reversed(damage)
                              if e.get("type") == "damage" and e.get("sourceID") == source
                              and e.get("amount", 0) > 0 and e.get("hitType") != 10
                              and not e.get("tick")}
            seen = set()
            for e in own:
                key = e.get("packetID"), e.get("abilityGameID")
                if (_event_name(e, names) in consumers and key not in seen
                        and (name != "Infuriate" or key in landed_packets)):
                    seen.add(key)
                    time = landed_packets[key] if name == "Infuriate" else float(e["timestamp"])
                    reductions.append((time, float(amount)))
        if targetable.seconds is None or targetable.seconds > 0 and not targetable.intervals:
            from .cooldown_timing import CooldownTiming
            rows.append(CooldownTiming(label, None, None, charges > 1))
        else:
            rows.append(cooldown_timing(label, times, recast * 1000, charges, start, end,
                                        living, tuple(reductions)))
    return tuple(rows)


def buff_intervals(rule, buffs, names, source, end, damage_windows):
    ids = {id_ for id_, name in names.items() if name == rule.status}
    if rule.kind == "damage":
        return tuple((a, min(b, end), strength) for id_ in ids
                     for a, b, strength in damage_windows.get(id_, ()))
    active = None
    intervals = []
    for event in sorted(buffs, key=lambda e: e.get("timestamp", 0)):
        if (event.get("targetID") != source or event.get("sourceID") not in {source, None}
                or event.get("abilityGameID") not in ids):
            continue
        time = event["timestamp"]
        if event.get("type") in {"applybuff", "refreshbuff"}:
            if active is not None:
                intervals.append((active[0], min(time, active[1], end), rule.strength))
            active = (time, time + event.get("duration", rule.duration_ms))
        elif event.get("type") == "removebuff":
            if active is not None:
                intervals.append((active[0], min(time, active[1], end), rule.strength))
                active = None
            else:
                # A removal can establish an opening aura, but without a
                # recorded grant its start cannot be reconstructed reliably.
                continue
    if active is not None:
        intervals.append((*active[:1], min(active[1], end), rule.strength))
    return tuple((a, b, strength) for a, b, strength in intervals if b > a)


def summarize_alignment(job, rows, buffs, names, source, start, end, damage_windows,
                        profile, guaranteed_packets):
    results = []
    for rule in rules_for(job).ALIGNMENT:
        intervals = buff_intervals(rule, buffs, names, source, end, damage_windows)
        totals = [[0.0, 0.0] for _ in intervals]
        inside = outside = 0.0
        findings: dict[str, tuple[set[tuple[Any, Any]], float, float]] = {}
        relevant_ids = {id_ for id_, name in names.items() if name == rule.status}
        for event, time, name, potency in rows:
            if name not in rule.actions:
                continue
            key = event.get("packetID"), event.get("abilityGameID")
            interval = next((i for i, (a, b, _) in enumerate(intervals) if a <= time < b), None)
            enhanced = (key in guaranteed_packets if rule.name == "Reassemble" else
                        any(_has_buff(event, id_) for id_ in relevant_ids))
            if rule.kind == "damage":
                factor = self_damage_multiplier(str(event.get("buffs", "")), time,
                    {id_: windows for id_, windows in damage_windows.items() if id_ in relevant_ids})
                enhanced = factor > 1
                potency /= factor
            if enhanced:
                inside += potency
            else:
                outside += potency
            nearest = interval if interval is not None else min(
                range(len(intervals)), key=lambda i: (max(intervals[i][0] - time,
                    time - intervals[i][1], 0), abs(time - intervals[i][0])), default=None)
            if nearest is not None:
                totals[nearest][0 if enhanced else 1] += potency
            if not enhanced:
                # Rate/guaranteed estimates are expected damage equivalents,
                # kept separate from base potency and never added to PPS.
                baseline = (1 + profile.critical_rate * (profile.critical_damage_multiplier - 1)) * (1 + .25 * profile.direct_rate)
                if rule.kind == "damage":
                    strength = intervals[nearest][2] if nearest is not None else rule.strength
                    gain = potency * (strength - 1)
                elif rule.kind == "guaranteed":
                    strength = profile.critical_damage_multiplier * 1.25 * profile.guaranteed_direct_multiplier
                    gain = potency * max(0, strength - baseline)
                else:
                    # Inherently guaranteed Starfall Dance converts Devilment
                    # rate bonuses instead of rolling extra Crit/DH chances.
                    if name == "Starfall Dance":
                        critical = floor((1 + rule.strength * (profile.critical_damage_multiplier - 1)) * 1000 + 1e-9) / 1000
                        direct = floor((1 + .25 * rule.strength) * 1000 + 1e-9) / 1000
                        gain = potency * profile.critical_damage_multiplier * 1.25 * profile.guaranteed_direct_multiplier * (critical * direct - 1)
                    else:
                        strength = (1 + min(1, profile.critical_rate + rule.strength) * (profile.critical_damage_multiplier - 1)) * (1 + .25 * min(1, profile.direct_rate + rule.strength))
                        gain = potency * max(0, strength - baseline)
                packet = key if key[0] is not None else (time, name)
                packets, previous, previous_gain = findings.get(name, (set(), 0.0, 0.0))
                packets.add(packet)
                findings[name] = packets, previous + potency, previous_gain + gain
        results.append(BurstAlignment(rule.name, rule.kind, rule.actions, inside, outside,
            tuple(AlignmentWindow((a - start) / 1000, (b - start) / 1000, *total)
                  for (a, b, _), total in zip(intervals, totals)),
            tuple(OutsideAction(name, len(value[0]), value[1], value[2])
                  for name, value in sorted(findings.items(), key=lambda r: (-r[1][2], r[0]))),
            bool(intervals)))
    return tuple(results)


def omission_reason(begin, deadline, end, life, source, targetable, expired=False):
    if any(e.get("type") == "death" and e.get("targetID") == source
           and begin <= e["timestamp"] < min(deadline, end) for e in life):
        return "player died during sequence"
    if any(b < min(deadline, end) and not any(a < min(deadline, end) and c > max(begin, b)
           for a, c in targetable.intervals) for _, b in targetable.intervals):
        return "boss downtime during sequence"
    if end < deadline:
        return "fight ended during sequence"
    if expired:
        return "ready effect expired"
    return "reason unconfirmed"


def summarize_follow_ups(job, casts, damage, buffs, names, life, source, start, end,
                         targetable, hit_failures):
    groups = {}
    own = [e for e in casts if e.get("sourceID") == source and not e.get("fake")
           and e.get("type", "cast") == "cast"]
    landed = {(e.get("packetID"), e.get("abilityGameID")) for e in damage
              if e.get("sourceID") == source and e.get("type") == "damage"
              and not e.get("tick") and not e.get("fake")
              and e.get("amount", 0) > 0 and e.get("hitType") != 10}
    for rule in rules_for(job).FOLLOW_UPS:
        status_ids = {id_ for id_, name in names.items() if name == rule.status}
        grants = []
        packets = {}
        for e in sorted(buffs, key=lambda e: e.get("timestamp", 0)):
            if (e.get("targetID") != source or e.get("sourceID") not in {source, None}
                    or e.get("abilityGameID") not in status_ids
                    or e.get("type") not in {"applybuff", "refreshbuff"}):
                continue
            packet = e.get("packetID")
            if packet is not None and packet in packets:
                previous = packets[packet]
                previous[1] = max(previous[1], e["timestamp"] + e.get("duration", rule.duration_ms))
            else:
                grant = [e["timestamp"], e["timestamp"] + e.get("duration", rule.duration_ms)]
                grants.append(grant)
                if packet is not None:
                    packets[packet] = grant
        for i, (begin, expiry) in enumerate(grants):
            if begin >= end:
                continue
            next_grant = grants[i + 1][0] if i + 1 < len(grants) else end
            deadline = min(expiry, next_grant, end)
            consumers = [e for e in own if begin - 100 <= e["timestamp"] <= deadline
                         and (e["timestamp"] < next_grant or next_grant == end)
                         and _event_name(e, names) in rule.actions
                         and not any(d.get("type") == "death" and d.get("targetID") == source
                                     and begin <= d["timestamp"] < e["timestamp"] for d in life)]
            removals = [e["timestamp"] for e in buffs
                        if e.get("type") == "removebuff" and e.get("targetID") == source
                        and e.get("sourceID") in {source, None}
                        and e.get("abilityGameID") in status_ids
                        and begin <= e["timestamp"] < min(expiry - 100, deadline)
                        and not any(abs(c["timestamp"] - e["timestamp"]) <= 1000
                                    for c in consumers)]
            removed = min(removals, default=None)
            if removed is not None:
                deadline = min(deadline, removed)
                consumers = [e for e in consumers if e["timestamp"] <= deadline]
            used = set()
            for cast in consumers:
                key = cast.get("packetID"), cast.get("abilityGameID")
                if key in used:
                    continue
                used.add(key)
                if rule.requires_hit and key not in landed:
                    seconds = (cast["timestamp"] - start) / 1000
                    action = _event_name(cast, names)
                    reason = hit_failures.get((action, seconds), "reason unconfirmed")
                    reason = {"downtime": "boss downtime", "fight ending": "fight ended before hit landed",
                              "unconfirmed": "reason unconfirmed"}.get(reason, reason)
                    groups.setdefault((seconds, "cast, no hit", reason), []).append(action)
            if len(used) < rule.charges:
                missing = rule.name if rule.charges == 1 else f"{rule.name}: {len(used)}/{rule.charges} casts"
                progress = max([begin, *(e["timestamp"] for e in consumers)])
                deaths = [e for e in life if e.get("timestamp", 0) < deadline]
                expired = removed is None and expiry <= end and expiry <= next_grant
                reason = omission_reason(progress, expiry if deadline == end else deadline,
                                         end, deaths, source, targetable, expired)
                if removed is not None and reason == "reason unconfirmed":
                    nearby_death = any(d.get("type") == "death" and d.get("targetID") == source
                                       and begin <= d["timestamp"] <= end
                                       and abs(d["timestamp"] - removed) <= 250 for d in life)
                    reason = "player died during sequence" if nearby_death else f"{rule.status} removed; reason unconfirmed"
                if reason == "ready effect expired":
                    reason = f"{rule.status} expired"
                elif next_grant < expiry and next_grant < end and reason == "reason unconfirmed":
                    reason = "ready effect overwritten"
                outcome = "missing" if rule.charges == 1 else "incomplete"
                groups.setdefault(((begin - start) / 1000, outcome, reason), []).append(missing)
    return tuple(FollowUpContext(seconds, tuple(dict.fromkeys(actions)), outcome, reason)
                 for (seconds, outcome, reason), actions in sorted(groups.items()))
