"""Count observed procs and bound unlogged Feather Gauge gains."""

import re
from typing import Any

from ..events import _event_name
from ..models import DncProcSummary
from .luck import combined_feather_luck, proc_luck
from .ready_procs import FAMILIES, summarize_ready_procs

CHANCE = re.compile(
    r"(?:Additional Effect|Combo Bonus): (\d+)% chance of granting "
    r"(a Fourfold Feather|Threefold Fan Dance|Silken Symmetry|Silken Flow)"
)


def summarize_dnc_procs(
    casts: list[dict[str, Any]],
    damage: list[dict[str, Any]],
    buffs: list[dict[str, Any]] | None,
    life: list[dict[str, Any]],
    abilities: dict[int, str],
    actions: dict[str, dict[str, Any]],
    source_id: int | None,
    *,
    starting_feathers: tuple[int, ...] = tuple(range(5)),
    starting_source: str = "unknown",
    fight_start: float = 0,
) -> DncProcSummary:
    rules = {}
    for name, action in actions.items():
        match = CHANCE.search(" ".join(action.get("description", [])))
        if match:
            rules[name] = (match[2], int(match[1]) / 100)
    own_casts = [e for e in casts if e.get("sourceID") == source_id and not e.get("fake")]
    by_packet = {(e.get("packetID"), e.get("abilityGameID")): e for e in own_casts}
    cast_names = {e.get("packetID"): _event_name(e, abilities) for e in own_casts}
    # A successful resolution can grant a resource even when the later damage ghosts.
    # One AoE packet is one roll, regardless of its number of targets.
    resolutions = {}
    for event in damage:
        if (
            event.get("sourceID") != source_id
            or event.get("packetID") is None
            or event.get("type") not in {"damage", "calculateddamage"}
            or event.get("hitType") == 10
            or event.get("amount", 0) <= 0
        ):
            continue
        key = event["packetID"], event.get("abilityGameID")
        if key not in resolutions or event["timestamp"] < resolutions[key]["timestamp"]:
            resolutions[key] = event
    feathers = {
        k: e
        for k, e in resolutions.items()
        if rules.get(_event_name(e, abilities), (None,))[0] == "a Fourfold Feather"
    }
    fans = {
        k: e
        for k, e in resolutions.items()
        if rules.get(_event_name(e, abilities), (None,))[0] == "Threefold Fan Dance"
    }
    spenders = [
        e
        for e in own_casts
        if rules.get(_event_name(e, abilities), (None,))[0] == "Threefold Fan Dance"
    ]
    random_procs, guaranteed = set(), set()
    unassigned = False
    for event in buffs or []:
        if (
            event.get("sourceID") != source_id
            or event.get("targetID") != source_id
            or event.get("type") not in {"applybuff", "refreshbuff"}
            or _event_name(event, abilities) != "Threefold Fan Dance"
        ):
            continue
        extra = event.get("extraAbilityGameID")
        name = (abilities.get(extra, "") if isinstance(extra, int) else "") or cast_names.get(
            event.get("packetID"), ""
        )
        packet = event.get("packetID")
        if packet is None:
            unassigned = True
        elif rules.get(name, (None,))[0] == "Threefold Fan Dance":
            random_procs.add(packet)
        elif name == "Flourish":
            guaranteed.add(packet)
        else:
            unassigned = True
    # A proc application is itself evidence that the spender resolved.
    for key, cast in by_packet.items():
        if key[0] in random_procs:
            fans.setdefault(key, cast)
    timeline = [(e["timestamp"], 0, "gain") for e in feathers.values()]
    timeline += [(e["timestamp"], 1, "spend") for e in spenders]
    timeline += [
        (e["timestamp"], 2, "death")
        for e in life
        if e.get("type") == "death" and e.get("targetID") == source_id
    ]
    # Apply the encounter reset policy before following resource evidence. Each state
    # carries exact extrema for accepted gains and successful rolls (including cap losses).
    states = {inventory: (0, 0, 0, 0) for inventory in starting_feathers}
    for _, _, kind in sorted(timeline):
        next_states = {}
        for inventory, bounds in states.items():
            options = [(inventory, 0, 0), (min(4, inventory + 1), int(inventory < 4), 1)]
            if kind == "spend":
                options = [(inventory - 1, 0, 0)] if inventory else []
            elif kind == "death":
                options = [(0, 0, 0)]
            for new_inventory, gain, success in options:
                values = (
                    bounds[0] + gain,
                    bounds[1] + gain,
                    bounds[2] + success,
                    bounds[3] + success,
                )
                previous = next_states.get(new_inventory, values)
                next_states[new_inventory] = (
                    min(previous[0], values[0]),
                    max(previous[1], values[1]),
                    min(previous[2], values[2]),
                    max(previous[3], values[3]),
                )
        states = next_states
    ready_procs = summarize_ready_procs(
        own_casts, resolutions, buffs, life, abilities, rules, source_id, fight_start
    )
    full_use = 0.0
    for ready in ready_procs[:2]:
        if ready.guaranteed_grants is None:
            full_use = None
            break
        # A hypothetical full-use baseline separates initial proc luck from
        # the conditional expectations below. It assumes no readiness or cap losses.
        consumers = FAMILIES[ready.name][2]
        rates = {rules[name][1] for name in consumers if name in rules}
        if len(rates) != 1:
            full_use = None
            break
        full_use += (ready.expected + ready.guaranteed_grants) * rates.pop()
    fan_rates = {rate for status, rate in rules.values() if status == "Threefold Fan Dance"}
    full_use_threefold = (
        full_use * next(iter(fan_rates)) if full_use is not None and len(fan_rates) == 1 else None
    )
    ordinary_expected = 0.0
    chain_known = True
    for stage in ready_procs[:2]:
        rates = {rules[name][1] for name in FAMILIES[stage.name][2] if name in rules}
        if len(rates) != 1:
            chain_known = False
            break
        ordinary_expected += stage.expected * rates.pop()
    initial_trials = sum(count for stage in ready_procs[:2] for _, count in stage.trials)
    chain_chance = ordinary_expected / initial_trials if chain_known and initial_trials else None
    success_min = min((b[2] for b in states.values()), default=None)
    success_max = max((b[3] for b in states.values()), default=None)
    (initial_luck, feather_min, feather_max, threefold_luck) = proc_luck(
        ready_procs,
        rules,
        list(feathers.values()),
        abilities,
        success_min,
        success_max,
    )
    return DncProcSummary(
        combined_feather_luck_min=combined_feather_luck(ready_procs, len(feathers), success_min),
        gcd_to_feather_chance=chain_chance,
        starting_feathers=starting_feathers,
        starting_feathers_source=starting_source,
        initial_proc_luck=initial_luck,
        feather_luck_min=feather_min,
        feather_luck_max=feather_max,
        threefold_luck=threefold_luck,
        ready_procs=ready_procs,
        full_use_expected_feathers=full_use,
        full_use_expected_random_threefold=full_use_threefold,
        feather_trials=len(feathers),
        expected_feathers=sum(rules[_event_name(e, abilities)][1] for e in feathers.values()),
        feathers_used=len(spenders),
        feathers_gained_min=min((b[0] for b in states.values()), default=None),
        feathers_gained_max=max((b[1] for b in states.values()), default=None),
        feather_successes_min=min((b[2] for b in states.values()), default=None),
        feather_successes_max=max((b[3] for b in states.values()), default=None),
        fan_trials=len(fans),
        expected_threefold=sum(rules[_event_name(e, abilities)][1] for e in fans.values()),
        random_threefold=len(random_procs) if buffs is not None and not unassigned else None,
        guaranteed_threefold=len(guaranteed),
        fan_three_uses=sum(_event_name(e, abilities) == "Fan Dance III" for e in own_casts),
    )
