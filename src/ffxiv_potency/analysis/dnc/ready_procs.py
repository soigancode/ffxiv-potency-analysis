"""Follow random and Flourish readiness effects through consumption and loss."""

from collections import Counter
from typing import Any

from ..events import _event_name
from ..models import DncReadyProcSummary

FAMILIES = {
    "Symmetry": ("Silken Symmetry", "Flourishing Symmetry", {"Reverse Cascade", "Rising Windmill"}),
    "Flow": ("Silken Flow", "Flourishing Flow", {"Fountainfall", "Bloodshower"}),
    "Threefold": ("Threefold Fan Dance", "Threefold Fan Dance", {"Fan Dance III"}),
}


def summarize_ready_procs(
    casts: list[dict[str, Any]],
    resolutions: dict[tuple[Any, Any], dict[str, Any]],
    buffs: list[dict[str, Any]] | None,
    life: list[dict[str, Any]],
    abilities: dict[int, str],
    rules: dict[str, tuple[str, float]],
    source_id: int | None,
    fight_start: float = 0,
) -> tuple[DncReadyProcSummary, ...]:
    """Loss counts require explicit status evidence, never grant-minus-use guesses."""
    own = [
        e for e in buffs or [] if e.get("sourceID") == source_id and e.get("targetID") == source_id
    ]
    cast_names = {e.get("packetID"): _event_name(e, abilities) for e in casts}
    summaries = []
    for family, (random_status, guaranteed_status, consumers) in FAMILIES.items():
        events = [e for e in own if _event_name(e, abilities) in {random_status, guaranteed_status}]
        random_packets, guaranteed_packets = set(), set()
        unassigned = False
        for e in events:
            if e.get("type") not in {"applybuff", "refreshbuff"}:
                continue
            extra = e.get("extraAbilityGameID")
            name = (abilities.get(extra, "") if isinstance(extra, int) else "") or cast_names.get(
                e.get("packetID"), ""
            )
            packet = e.get("packetID")
            if packet is None:
                unassigned = True
            elif (
                _event_name(e, abilities) == random_status
                and rules.get(name, (None,))[0] == random_status
            ):
                random_packets.add(packet)
            elif _event_name(e, abilities) == guaranteed_status and name == "Flourish":
                guaranteed_packets.add(packet)
            else:
                unassigned = True
        trials = {}
        for key, e in resolutions.items():
            name = _event_name(e, abilities)
            if rules.get(name, (None,))[0] != random_status:
                continue
            # Flow comes from the combo bonus, not every Fountain/Bladeshower.
            bonus = e.get("bonusPercent")
            if random_status == "Silken Flow" and not (
                isinstance(bonus, (int, float)) and bonus > 0 or key[0] in random_packets
            ):
                continue
            trials[key] = name
        for c in casts:
            name = _event_name(c, abilities)
            if c.get("packetID") in random_packets and rules.get(name, (None,))[0] == random_status:
                trials.setdefault((c.get("packetID"), c.get("abilityGameID")), name)
        used = [c for c in casts if _event_name(c, abilities) in consumers]
        active: dict[str, dict[str, Any]] = {}
        consumed = {"random": set(), "guaranteed": set()}
        losses = Counter()
        loss_events = []
        seen = set()
        for e in sorted(events, key=lambda e: e["timestamp"]):
            status = _event_name(e, abilities)
            kind = e.get("type")
            identity = (
                status,
                e["timestamp"],
                e.get("packetID"),
                "grant" if kind in {"applybuff", "refreshbuff"} else kind,
            )
            if identity in seen:
                continue
            seen.add(identity)
            if kind in {"applybuff", "refreshbuff"}:
                if status in active:
                    losses["overwritten"] += 1
                    loss_events.append((e["timestamp"], status, "overwritten"))
                packet = e.get("packetID")
                origin = (
                    "random"
                    if packet in random_packets
                    else "guaranteed"
                    if packet in guaranteed_packets
                    else "unknown"
                )
                active[status] = {**e, "_origin": origin}
            elif kind == "removebuff":
                prior = active.pop(status, None)
                # A remove alone can consume an initial aura, but must not
                # invent a grant within the saved fight.
                # The provided logs contain one 1 ms cast/removal offset.
                # Keep the match narrow so nearby expiry is not consumption.
                consumer = min(
                    (c for c in used if abs(c["timestamp"] - e["timestamp"]) <= 1),
                    key=lambda c: abs(c["timestamp"] - e["timestamp"]),
                    default=None,
                )
                if consumer is not None:
                    origin = prior.get("_origin", "unknown") if prior else "unknown"
                    if origin in consumed:
                        consumed[origin].add((consumer.get("packetID"), consumer["timestamp"]))
                    else:
                        losses["unknown_consumed"] += 1
                elif any(
                    d.get("type") == "death"
                    and d.get("targetID") == source_id
                    and abs(d["timestamp"] - e["timestamp"]) <= 250
                    for d in life
                ):
                    losses["death"] += 1
                    loss_events.append((e["timestamp"], status, "death"))
                elif (
                    prior
                    and e["timestamp"] >= prior["timestamp"] + prior.get("duration", 30000) - 1000
                ):
                    losses["expired"] += 1
                    loss_events.append((e["timestamp"], status, "expired"))
                else:
                    losses["unknown"] += 1
        random_used, guaranteed_used = consumed["random"], consumed["guaranteed"]
        counts = Counter(trials.values())
        summaries.append(
            DncReadyProcSummary(
                family,
                tuple(sorted(counts.items())),
                sum(rules[name][1] for name in trials.values()),
                len(random_packets) if buffs is not None and not unassigned else None,
                len(guaranteed_packets) if buffs is not None and not unassigned else None,
                len(used),
                len(random_used),
                len(guaranteed_used),
                len(random_used & guaranteed_used),
                losses["overwritten"],
                losses["expired"],
                losses["death"],
                len(active),
                losses["unknown_consumed"],
                losses["unknown"],
                tuple(((time-fight_start)/1000, name, reason) for time, name, reason in loss_events),
            )
        )
    return tuple(summaries)
