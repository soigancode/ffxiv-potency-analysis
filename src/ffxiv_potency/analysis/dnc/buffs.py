"""Track Dancer's own Standard and Technical Finish strengths."""

from typing import Any

from ..buffs import damage_snapshot_times, self_damage_multiplier
from ..errors import AnalysisError
from ..events import _event_name

FINISH_STATUSES = {1001821: "Standard Finish", 1001822: "Technical Finish"}
# These statuses modify Crit/DH rate, not the FF Logs damage multiplier.
RATE_NAMES = {
    "Devilment",
    "Chain Stratagem",
    "Battle Litany",
    "Battle Voice",
    "Army's Paeon",
    "The Wanderer's Minuet",
    "Wanderer's Minuet",
}


def _initial_strength(status, actions, damage, abilities, windows, boundary, snapshot_times):
    """Fit rounded multipliers against later known finishes with identical raid buffs."""
    strengths = set(actions[FINISH_STATUSES[status]]["damage_buff"]["by_count"].values())
    plausible = set(strengths)
    samples = 0
    rate_statuses = {ability for ability, name in abilities.items() if name in RATE_NAMES}
    references = {}

    def snapshot(hit):
        time = snapshot_times.get(
            (hit.get("packetID"), hit.get("abilityGameID")), hit.get("timestamp", 0)
        )
        return (
            time - 0.001
            if actions.get(_event_name(hit, abilities), {}).get("damage_buff")
            else time
        )

    for hit in damage:
        if hit.get("type") != "damage" or snapshot(hit) < boundary:
            continue
        present = {int(s) for s in str(hit.get("buffs", "")).split(".") if s.isdigit()}
        own = present & FINISH_STATUSES.keys()
        time = snapshot(hit)
        if any(not any(start <= time < end for start, end, _ in windows.get(s, ())) for s in own):
            continue
        multiplier = hit.get("multiplier")
        if not isinstance(multiplier, (int, float)):
            continue
        factor = self_damage_multiplier(str(hit.get("buffs", "")), time, windows)
        factor *= 1.05 if 1000049 in present else 1
        external = frozenset(present - FINISH_STATUSES.keys() - {1000049} - rate_statuses)
        references.setdefault(external, []).append(
            ((multiplier - 0.0051) / factor, (multiplier + 0.0051) / factor)
        )
    for hit in damage:
        present = {int(s) for s in str(hit.get("buffs", "")).split(".") if s.isdigit()}
        if (
            hit.get("type") != "damage"
            or hit.get("amount", 0) <= 0
            or status not in present
            or snapshot(hit) >= boundary
        ):
            continue
        observed = hit.get("multiplier")
        if not isinstance(observed, (int, float)):
            continue
        potion = 1.05 if 1000049 in present else 1
        time = snapshot(hit)
        other = {s: intervals for s, intervals in windows.items() if s != status}
        factor = self_damage_multiplier(str(hit.get("buffs", "")), time, other) * potion
        external = frozenset(present - FINISH_STATUSES.keys() - {1000049} - rate_statuses)
        bounds = references.get(external, []) if external else [(1, 1)]
        if not bounds:
            continue
        lower = max(lo for lo, _ in bounds)
        upper = min(hi for _, hi in bounds)
        # Identical status IDs do not guarantee identical buff strengths.
        # Radiant Finale, for example, varies with Coda. Contradictory later
        # references cannot constrain the initial aura, but other groups can.
        if lower > upper:
            continue
        plausible &= {
            s
            for s in strengths
            if (observed - 0.0051) / (s * factor) <= upper
            and (observed + 0.0051) / (s * factor) >= lower
        }
        samples += 1
    if samples and len(plausible) == 1:
        return plausible.pop()
    raise AnalysisError(f"cannot determine pre-pull {FINISH_STATUSES[status]} strength")


def dnc_self_buff_windows(
    casts: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    abilities: dict[int, str],
    actions: dict[str, dict[str, Any]],
    source_id: int,
    start: int,
    end: int,
    combatants: list[dict[str, Any]] | None,
    damage: list[dict[str, Any]],
) -> tuple[dict[int, tuple[tuple[int, int, float], ...]], tuple[tuple[str, float], ...]]:
    active: dict[int, tuple[int, int, float]] = {}
    completed: dict[int, list[tuple[int, int, float]]] = {}
    own = [
        e
        for e in buffs
        if e.get("sourceID") == source_id
        and e.get("targetID") == source_id
        and e.get("abilityGameID") in FINISH_STATUSES
    ]
    by_packet = {
        e.get("packetID"): actions.get(_event_name(e, abilities), {})
        for e in casts
        if e.get("sourceID") == source_id and e.get("packetID") is not None
    }
    for event in sorted(own, key=lambda e: e.get("timestamp", 0)):
        status = event["abilityGameID"]
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, int):
            continue
        previous = active.pop(status, None)
        if previous:
            completed.setdefault(status, []).append(
                (previous[0], min(previous[1], timestamp), previous[2])
            )
        if event.get("type") == "removebuff":
            continue
        if event.get("type") not in {"applybuff", "refreshbuff"}:
            continue
        extra = event.get("extraAbilityGameID")
        action = actions.get(abilities.get(extra, ""), {}) if isinstance(extra, int) else {}
        if not action.get("damage_buff"):
            action = by_packet.get(event.get("packetID"), {})
        rule = action.get("damage_buff")
        if not isinstance(rule, dict) or rule.get("status") != FINISH_STATUSES[status]:
            raise AnalysisError(f"cannot match {FINISH_STATUSES[status]} to its dance finish")
        count = action.get("completed_steps", 2 if action.get("name") == "Finishing Move" else None)
        strength = rule["by_count"].get(str(count))
        if not isinstance(strength, (int, float)):
            raise AnalysisError(f"unknown step count for {FINISH_STATUSES[status]}")
        active[status] = (
            timestamp,
            min(end, timestamp + rule["duration_seconds"] * 1000),
            strength,
        )
    for status, window in active.items():
        completed.setdefault(status, []).append(window)
    initial = next((c for c in combatants or [] if c.get("sourceID") == source_id), {})
    snapshots = damage_snapshot_times(damage, casts)
    inferred = []
    for aura in initial.get("auras", []):
        status = aura.get("ability")
        if status not in FINISH_STATUSES or aura.get("source") != source_id:
            continue
        boundary = min(
            (e["timestamp"] for e in own if e.get("abilityGameID") == status), default=end
        )
        strength = _initial_strength(
            status, actions, damage, abilities, completed, boundary, snapshots
        )
        completed.setdefault(status, []).insert(0, (start - 1, boundary, strength))
        inferred.append((FINISH_STATUSES[status], strength))
    return {status: tuple(windows) for status, windows in completed.items()}, tuple(inferred)
