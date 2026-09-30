"""Match an opening Queen against later, reconstructed Queen deployments."""

from collections import defaultdict
from dataclasses import replace
from typing import Any

from ..events import _event_name, _has_buff
from ..models import PetDeploymentSummary
from ..pets import _deployment_for_event


def mch_queen_hits(damage, actors, actions, names, source_id, excluded_statuses=()):
    """Use landed Queen hits; retain calculated timestamps for deployment matching."""
    times = {(e.get("packetID"), e.get("abilityGameID"), e.get("sourceID")): e["timestamp"]
             for e in damage if isinstance(e, dict) and e.get("type") == "calculateddamage"}
    hits = []
    for event in damage:
        if not isinstance(event, dict):
            continue
        name = _event_name(event, names)
        action = actions.get(name, {})
        actor = actors.get(event.get("sourceID"), {})
        amount = event.get("amount")
        multiplier = event.get("multiplier", 1)
        if (event.get("type") != "damage" or action.get("source_actor") != "Automaton Queen"
                or actor.get("petOwner") != source_id or event.get("hitType") not in {1, 2}
                or not isinstance(amount, (int, float)) or amount <= 0
                or event.get("overkill", 0) > 0
                or not isinstance(multiplier, (int, float)) or multiplier <= .005
                or any(_has_buff(event, status) for status in (1000043, 1000044,
                                                             *excluded_statuses))):
            continue
        timestamp = times.get((event.get("packetID"), event.get("abilityGameID"),
                               event.get("sourceID")), event.get("timestamp"))
        if isinstance(timestamp, (int, float)):
            hits.append({**event, "_name": name, "_time": timestamp})
    return sorted(hits, key=lambda e: e["_time"])


def mch_has_prepull_queen(hits, casts, names, source_id) -> bool:
    if not hits:
        return False
    summons = [c["timestamp"] for c in casts if c.get("sourceID") == source_id
               and _event_name(c, names) == "Automaton Queen"]
    return not summons or hits[0]["_time"] < min(summons)


def infer_mch_opening_queen(
    hits: list[dict[str, Any]], deployments: tuple[PetDeploymentSummary, ...],
    actions: dict[str, dict[str, Any]], fight_start: float, prepull: bool,
) -> tuple[PetDeploymentSummary, ...]:
    if not hits or not (prepull or deployments and deployments[0].gauge_assumed):
        return deployments
    first = hits[0]
    instance = (first.get("sourceID"), first.get("sourceInstance"))
    if instance[1] is not None:
        target = [h for h in hits if (h.get("sourceID"), h.get("sourceInstance")) == instance]
    else:
        end = (deployments[0].timestamp_seconds if prepull else
               deployments[1].timestamp_seconds if len(deployments) > 1 else float("inf"))
        target = [h for h in hits if h["_time"] < fight_start + end * 1000]
    target_ids = {id(h) for h in target}

    def key(hit):
        return hit["_name"], hit["hitType"] == 2, _has_buff(hit, 1000049)

    def interval(hit, gauge):
        potency = actions[hit["_name"]].get("potency", {})
        base = potency.get("base")
        maximum = potency.get("gauge_scaling", {}).get("maximum_potency")
        if not isinstance(base, int) or not isinstance(maximum, int):
            return None
        value = base + (maximum - base) * (gauge - 50) / 50
        dh = 1.25 if hit.get("directHit") else 1
        m = hit.get("multiplier", 1)
        # Preserve roll variance and the rounded FF Logs multiplier. Match Crit
        # to Crit references so no configured gear Crit multiplier is assumed.
        return ((hit["amount"] - 2) / (value * dh * (m + .005) * 1.05),
                (hit["amount"] + 2) / (value * dh * (m - .005) * .95))

    references = defaultdict(list)
    reference_queens = set()
    for hit in hits:
        if id(hit) in target_ids:
            continue
        queen = _deployment_for_event("Automaton Queen", hit["_time"], deployments, fight_start)
        if queen is None or queen.gauge_assumed:
            continue
        # A pre-pull deployment invalidates the inherited starting Battery.
        # Exclude the first in-fight Queen from the reference baseline as well.
        if prepull and deployments and queen is deployments[0]:
            continue
        bounds = interval(hit, queen.gauge_spent)
        if bounds is not None:
            references[key(hit)].append(bounds)
            reference_queens.add(queen)
    if len(reference_queens) < 2:
        return deployments
    bounds = {k: (max(v[0] for v in values), min(v[1] for v in values))
              for k, values in references.items()}
    comparable = [h for h in target if key(h) in bounds
                  and bounds[key(h)][0] <= bounds[key(h)][1]]
    if len(comparable) < 2:
        return deployments
    candidates = []
    for gauge in range(50, 101, 10):
        fitted = dict(bounds)
        for hit in comparable:
            observed = interval(hit, gauge)
            if observed is None:
                break
            lower, upper = fitted[key(hit)]
            fitted[key(hit)] = max(lower, observed[0]), min(upper, observed[1])
        else:
            if all(fitted[key(h)][0] <= fitted[key(h)][1] for h in comparable):
                candidates.append(gauge)
    if len(candidates) != 1:
        return deployments
    if prepull:
        opening = PetDeploymentSummary(
            "Automaton Queen", min(0, (first["_time"] - fight_start) / 1000),
            "Battery Gauge", candidates[0], mch_gauge_inferred=True, mch_prepull=True,
        )
        return (opening, *deployments)
    if not deployments:
        return deployments
    return (replace(deployments[0], gauge_spent=candidates[0], gauge_assumed=False,
                    mch_gauge_inferred=True), *deployments[1:])
