"""Recorded Inner Release sequences and potion damage windows."""

from dataclasses import dataclass

from ..events import _event_name, _has_buff
from .buffs import INNER_RELEASE, SURGING_TEMPEST


@dataclass(frozen=True, slots=True)
class WarBurst:
    seconds: float | None
    spenders: int
    rend: int
    ruination: int
    wrath: int


@dataclass(frozen=True, slots=True)
class WarPotionBurst:
    start_seconds: float | None
    end_seconds: float | None
    casts: tuple[tuple[str, int], ...]
    base_potency: float
    gained_potency: float
    unbuffed_hits: int


POTION_ACTIONS = (
    ("IR spenders", ("Fell Cleave", "Decimate")),
    ("Infuriate", ("Infuriate",)),
    ("Nascent Chaos", ("Inner Chaos", "Chaotic Cyclone")),
    ("Primal Rend", ("Primal Rend",)),
    ("Primal Ruination", ("Primal Ruination",)),
    ("Primal Wrath", ("Primal Wrath",)),
    ("Upheaval/Orogeny", ("Upheaval", "Orogeny")),
    ("Onslaught", ("Onslaught",)),
)


def _own_casts(casts, source):
    own = []
    seen = set()
    for e in sorted(casts, key=lambda e: e["timestamp"]):
        key = ((e["packetID"], e.get("abilityGameID")) if e.get("packetID") is not None
               else ("event", id(e)))
        if (e.get("sourceID") == source and not e.get("fake")
                and e.get("type", "cast") == "cast" and key not in seen):
            seen.add(key)
            own.append(e)
    return own


def _spender_casts(sequence, buffs, source, begin, finish, prepull=False):
    grants = [e for e in buffs if e.get("sourceID") == source
              and e.get("targetID") == source and e.get("abilityGameID") == INNER_RELEASE
              and e.get("type") in {"applybuff", "refreshbuff"}
              and begin <= e["timestamp"] <= begin + 1000]
    ir_start = min((e["timestamp"] for e in grants), default=begin)
    removals = [e["timestamp"] for e in buffs if e.get("targetID") == source
                and e.get("abilityGameID") == INNER_RELEASE and e.get("type") == "removebuff"
                and ir_start <= e["timestamp"] < finish]
    ir_end = min(finish, min(removals, default=finish),
                 finish if prepull else ir_start + 15000)
    seen = set()
    selected = []
    for e, name in sequence:
        key = ((e["packetID"], e.get("abilityGameID")) if e.get("packetID") is not None
               else ("event", id(e)))
        if (name in {"Fell Cleave", "Decimate"} and ir_start <= e["timestamp"] <= ir_end
                and e["timestamp"] < finish and key not in seen and len(selected) < 3):
            seen.add(key)
            selected.append(e)
    return selected


def summarize_bursts(casts, damage, buffs, combatants, names, source, start, end):
    own = _own_casts(casts, source)
    triggers = [e for e in own if _event_name(e, names) == "Inner Release"]
    initial = any(a.get("ability") == INNER_RELEASE for c in combatants or ()
                  if c.get("sourceID") == source for a in c.get("auras", ()))
    if initial and (not triggers or triggers[0]["timestamp"] > start):
        observed_start = min((e["timestamp"] for e in own), default=start)
        triggers.insert(0, {"timestamp": min(start, observed_start), "_prepull": True})
    rows = []
    for i, trigger in enumerate(triggers):
        begin = trigger["timestamp"]
        finish = min(end, triggers[i + 1]["timestamp"] if i + 1 < len(triggers) else end)
        sequence = [e for e in own if begin <= e["timestamp"] < finish]
        spenders = _spender_casts([(e, _event_name(e, names)) for e in sequence],
                                  buffs, source, begin, finish, bool(trigger.get("_prepull")))
        rend = [e for e in sequence if _event_name(e, names) == "Primal Rend"
                and e["timestamp"] < (finish if trigger.get("_prepull") else begin + 30000)]
        ruination = [e for e in sequence if _event_name(e, names) == "Primal Ruination"
                     and any(r["timestamp"] <= e["timestamp"] < r["timestamp"] + 20000
                             for r in rend)]
        wrath = [e for e in sequence if _event_name(e, names) == "Primal Wrath"]
        rows.append(WarBurst(None if trigger.get("_prepull") else (begin - start) / 1000,
                             len(spenders), len(rend), len(ruination), len(wrath)))
    return tuple(rows)


def summarize_potion_bursts(casts, rows, windows, names, source, start, potion_id, multiplier,
                           buffs=(), end=float("inf")):
    """Use recorded snapshot buffs for damage; count casts separately from hits."""
    own = _own_casts(casts, source)
    ir_keys = set()
    triggers = sorted(e["timestamp"] for e in own if _event_name(e, names) == "Inner Release")
    for i, begin in enumerate(triggers):
        finish = min(end, triggers[i + 1] if i + 1 < len(triggers) else end)
        sequence = [(e, _event_name(e, names)) for e in own if begin <= e["timestamp"] < finish]
        ir_keys.update((e.get("packetID"), e.get("abilityGameID")) for e in
                       _spender_casts(sorted(sequence, key=lambda row: row[0]["timestamp"]),
                                      buffs, source, begin, finish))
    ir_keys.update((e.get("packetID"), e.get("abilityGameID")) for e, _, _, _ in rows
                   if _has_buff(e, INNER_RELEASE))
    grouped = [[] for _ in windows]
    for event, time, name, potency in rows:
        if not _has_buff(event, potion_id):
            continue
        seconds = (time - start) / 1000
        # A snapshot can precede the recorded potion cast or inferred boundary.
        # The recorded buff is authoritative; assign it to the nearest window.
        if windows:
            def distance(i, seconds=seconds):
                w = windows[i]
                begin = w.start_seconds if w.start_seconds is not None else w.observed_start_seconds
                finish = w.end_seconds if w.end_seconds is not None else w.observed_end_seconds
                return max((begin or 0) - seconds, seconds - (finish or begin or 0), 0)
            index = min(range(len(windows)), key=distance)
            grouped[index].append((event, time, name, potency))
    result = []
    for window, hits in zip(windows, grouped):
        packets = {(e.get("packetID"), e.get("abilityGameID")) for e, _, _, _ in hits
                   if e.get("packetID") is not None and not e.get("tick")}
        counts = []
        for label, consumers in POTION_ACTIONS:
            seen = set()
            for e in own:
                seconds = (e["timestamp"] - start) / 1000
                key = e.get("packetID"), e.get("abilityGameID")
                within = (window.start_seconds is not None and window.end_seconds is not None
                          and window.start_seconds <= seconds < window.end_seconds)
                if _event_name(e, names) not in consumers or not (within or key in packets):
                    continue
                if label == "IR spenders" and key not in ir_keys:
                    continue
                seen.add(key if e.get("packetID") is not None else ("event", id(e)))
            counts.append((label, len(seen)))
        potency = sum(p for _, _, _, p in hits)
        base = sum(e.get("_unpotted_potency", p / multiplier) for e, _, _, p in hits)
        unbuffed = sum((e.get("_tempest_factor") == 1 if "_tempest_factor" in e
                       else not _has_buff(e, SURGING_TEMPEST)) and name != "Damnation"
                       for e, _, name, _ in hits)
        result.append(WarPotionBurst(window.start_seconds, window.end_seconds, tuple(counts),
                                     base, potency - base, unbuffed))
    return tuple(result)
