"""Replay spell enhancements before consumption, independently of hit buff strings."""

from dataclasses import dataclass
from typing import Any

from ..events import _event_name
from ..execution import ReadyUse

DIVINE_MIGHT = 1002673
REQUIESCAT = 1001368
HOLY = frozenset({"Holy Spirit", "Holy Circle"})
BLADES = ("Confiteor", "Blade of Faith", "Blade of Truth", "Blade of Valor")


@dataclass(frozen=True, slots=True)
class PldSpell:
    name: str
    seconds: float
    packet: int | None
    ability_id: int
    enhancement: str
    cast_kind: str


@dataclass(frozen=True, slots=True)
class PldSpellState:
    spells: tuple[PldSpell, ...]
    ready: tuple[ReadyUse, ...]


def replay_spells(casts: list[dict[str, Any]], buffs: list[dict[str, Any]],
                  life: list[dict[str, Any]], combatants: list[dict[str, Any]],
                  names: dict[int, str], source: int, start: float, end: float) -> PldSpellState:
    own = [e for e in casts if e.get("sourceID") == source and not e.get("fake")]
    initial = {a["ability"]: a for c in combatants if c.get("sourceID") == source
               for a in c.get("auras", ()) if "ability" in a}
    statuses: tuple[int, ...] = (DIVINE_MIGHT, REQUIESCAT)
    counts: dict[int, int] = {
        s: int(initial[s].get("stacks", 4 if s == REQUIESCAT else 1))
        if s in initial else 0 for s in statuses
    }
    expires: dict[int, float | None] = {
        s: start + initial[s]["duration"] if s in initial and isinstance(
            initial[s].get("duration"), (int, float)) else None for s in statuses
    }
    grants: dict[int, int] = dict(counts)
    uses: dict[int, int] = dict.fromkeys(statuses, 0)
    expired: dict[int, int] = dict.fromkeys(statuses, 0)
    overwritten: dict[int, int] = dict.fromkeys(statuses, 0)
    dead: dict[int, int] = dict.fromkeys(statuses, 0)
    losses: dict[int, list[tuple[float, str]]] = {s: [] for s in statuses}
    grant_packets: dict[int, set[int]] = {s: set() for s in statuses}
    grant_times: dict[int, float | None] = dict.fromkeys(statuses)
    # Recorded grants establish state, casts read it, then recorded consumption
    # reconciles the remaining stacks. This preserves same-timestamp snapshots.
    timeline = [(e["timestamp"], {"applybuff": 0, "refreshbuff": 0,
                                 "applybuffstack": 1}.get(e["type"], 3), e)
        for e in buffs if e.get("targetID") == source
        and e.get("sourceID") in {source, None} and e.get("abilityGameID") in statuses]
    timeline += [(e["timestamp"], 2, e) for e in own if e.get("type") == "cast"
                 and _event_name(e, names) in HOLY | frozenset(BLADES) | {"Clemency"}]
    timeline += [(e["timestamp"], 3, e) for e in life
                 if e.get("targetID") == source and e.get("type") == "death"]
    spells = []
    begins: dict[str, list[dict[str, Any]]] = {}
    for e in own:
        if e.get("type") == "begincast":
            begins.setdefault(_event_name(e, names), []).append(e)

    def lose(status: int, time: float, reason: str, totals: dict[int, int]) -> None:
        if counts[status]:
            totals[status] += counts[status]
            losses[status].append(((time - start) / 1000, f"{counts[status]} {reason}"))
            counts[status] = 0

    for time, _, e in sorted(timeline, key=lambda row: row[:2]):
        for s in statuses:
            expiry = expires[s]
            if counts[s] and expiry is not None and time > expiry:
                lose(s, expiry, "expired", expired)
        kind = e["type"]
        s = e.get("abilityGameID")
        if kind == "cast":
            name = _event_name(e, names)
            enhancement = "Divine Might" if name in HOLY and counts[DIVINE_MIGHT] else (
                "Requiescat" if name != "Clemency" and counts[REQUIESCAT] else "None")
            status = DIVINE_MIGHT if enhancement == "Divine Might" else REQUIESCAT
            # Clemency consumes Requiescat's instant-cast charge without damage.
            if enhancement != "None" or (name == "Clemency" and counts[REQUIESCAT]):
                counts[status] -= 1
                uses[status] += 1
            if name == "Clemency":
                continue
            begin = next((b for b in sorted(begins.get(name, ()),
                                            key=lambda b: b["timestamp"], reverse=True)
                          if 0 < time - b["timestamp"] <= b.get("duration", 1500)
                          and not any(c.get("type") == "cast"
                                      and b["timestamp"] < c["timestamp"] < time for c in own)), None)
            if begin is not None:
                begins[name].remove(begin)
            cast_kind = "hard cast" if begin is not None else (
                "instant" if enhancement != "None" or name in BLADES else "unconfirmed")
            spells.append(PldSpell(name, (time - start) / 1000, e.get("packetID"),
                                   e["abilityGameID"], enhancement, cast_kind))
        elif kind == "death":
            for status in statuses:
                lose(status, time, "lost on death", dead)
        elif not isinstance(s, int) or s not in statuses:
            continue
        elif kind in {"applybuff", "refreshbuff"}:
            packet = e.get("packetID")
            if packet is not None and packet in grant_packets[s]:
                continue
            if packet is not None:
                grant_packets[s].add(packet)
            lose(s, time, "overwritten", overwritten)
            counts[s] = int(e.get("stack", 4 if s == REQUIESCAT else 1))
            grants[s] += counts[s]
            grant_times[s] = time
            expires[s] = time + e.get("duration", 30000)
        elif kind == "applybuffstack":
            # The stack row accompanies the preceding grant, not a second grant.
            stack = e.get("stack")
            if isinstance(stack, int):
                grants[s] += (stack - counts[s] if grant_times[s] == time
                              else max(0, stack - counts[s]))
                counts[s] = stack
                if isinstance(e.get("duration"), (int, float)):
                    expires[s] = time + e["duration"]
        elif kind == "removebuffstack":
            if isinstance(e.get("stack"), int):
                counts[s] = e["stack"]
        elif kind == "removebuff":
            expiry = expires[s]
            if counts[s] and expiry is not None and time >= expiry:
                lose(s, time, "expired", expired)
            elif any(d.get("type") == "death" and d.get("targetID") == source
                     and abs(d["timestamp"] - time) <= 250 for d in life):
                lose(s, time, "lost on death", dead)
            # An unexplained removal establishes absence, not a resource loss.
            counts[s] = 0
    for s in statuses:
        expiry = expires[s]
        if counts[s] and expiry is not None and expiry < end:
            lose(s, expiry, "expired", expired)
    return PldSpellState(tuple(spells), tuple(
        ReadyUse("Divine Might" if s == DIVINE_MIGHT else "Requiescat charges",
                 grants[s], uses[s], expired[s], overwritten[s], dead[s], counts[s],
                 tuple(losses[s]), uses[s]) for s in statuses
    ))
