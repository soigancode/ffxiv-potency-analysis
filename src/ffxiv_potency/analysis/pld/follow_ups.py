"""Recorded context for absent Paladin burst casts and landed hits."""

from dataclasses import dataclass

from ..events import _event_name
from .state import BLADES


@dataclass(frozen=True, slots=True)
class PldFollowUpIssue:
    actions: tuple[str, ...]
    kind: str
    reason: str
    effect: str | None = None


def follow_up_issues(trigger, follows, rows, names, ready, buffs, life, source,
                     start, end, finish, targetable=None, hit_failures=None
                     ) -> tuple[PldFollowUpIssue, ...]:
    """Group identical contexts, retaining unconfirmed omissions as such.

    Missing-cast context is bounded by the recorded ready-effect lifetime,
    rather than the whole interval until the next minute-long burst cycle.
    """
    begin = trigger["timestamp"]
    grants = [e for e in buffs if e.get("abilityGameID") in {1001368, 1003019, 1003831}
              and e.get("type") in {"applybuff", "refreshbuff"}
              and begin <= e["timestamp"] < min(finish, begin + 2500)]
    ready_end = max([begin + 30000, *(
        e["timestamp"] + e.get("duration", 30000) for e in grants
    )])
    deadline = min(finish, ready_end)
    deaths = [e["timestamp"] for e in life
              if e.get("type") == "death" and e.get("targetID") == source]
    groups: dict[tuple[str, str, str | None], list[str]] = {}

    def record(name, kind, reason, effect=None):
        group = groups.setdefault((kind, reason, effect), [])
        if name not in group:
            group.append(name)

    for row in rows:
        casts = [e for e in follows if _event_name(e, names) == row.name]
        if casts and not row.hits:
            for cast in casts:
                seconds = (cast["timestamp"] - start) / 1000
                reason = (hit_failures or {}).get((row.name, seconds), "unconfirmed")
                record(row.name, "no_hit", reason)
        elif not casts:
            if trigger.get("abilityGameID") == -1:
                record(row.name, "missing_cast", "prepull")
                continue
            preceding = BLADES[:BLADES.index(row.name)] if row.name in BLADES else ()
            progress = max([begin, *(e["timestamp"] for e in follows
                                    if _event_name(e, names) in preceding)])
            if progress >= deadline:
                record(row.name, "missing_cast", "unconfirmed")
                continue
            if any(progress <= time < deadline for time in deaths):
                record(row.name, "missing_cast", "death")
                continue
            # A recorded gap must continue through the ready window's end.
            # A short gap followed by resumed combat does not explain omission.
            intervals = targetable.intervals if targetable is not None else ()
            if any(b < deadline
                   and not any(a < deadline and c > max(progress, b) for a, c in intervals)
                   for _, b in intervals):
                record(row.name, "missing_cast", "downtime")
                continue
            effects = (("Confiteor",) if row.name == "Confiteor" else
                       ("Blade of Honor",) if row.name == "Blade of Honor" else
                       ("Requiescat charges",))
            expiry = next((effect.name for effect in ready if effect.name in effects
                           and any((progress - start) / 1000 <= seconds <= (deadline - start) / 1000
                                   and "expired" in reason
                                   for seconds, reason in effect.losses)), None)
            if expiry is not None:
                record(row.name, "missing_cast", "expiry", expiry)
            elif finish == end and end < ready_end:
                record(row.name, "missing_cast", "fight_end")
            else:
                record(row.name, "missing_cast", "unconfirmed")
    return tuple(PldFollowUpIssue(tuple(actions), kind, reason, effect)
                 for (kind, reason, effect), actions in groups.items())
