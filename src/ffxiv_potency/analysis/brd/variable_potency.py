"""Infer Pitch Perfect, Apex Arrow, and Encore potency from landed damage."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

from ..consumables import food_active
from ..events import _event_name, _has_buff
from ..models import (
    BrdApexUseEstimate,
    BrdOutsideExpectedHit,
    BrdPitchHitEstimate,
    BrdPotencyEstimateSummary,
)
from .songs import _brd_coda


def _brd_damage_estimates(
    landed: list[dict[str, Any]],
    casts: list[dict[str, Any]],
    raw_damage: list[Any],
    names: dict[int, str],
    critical_multiplier: float,
    *,
    fight_start: float = 0.0,
    potion_multiplier: float = 1.0,
    potion_buff_id: int = 1000049,
    unfed_critical_multiplier: float | None = None,
    unfed_determination_ratio: float = 1.0,
    food_missing: tuple[tuple[float, float], ...] = (),
) -> tuple[dict[int, tuple[float, bool, float]], tuple[BrdPotencyEstimateSummary, ...]]:
    """Infer BRD variable potency from fixed attacks by the same player.

    The returned values are base potency, before applying the potion in the
    normal event loop. Uncertain hits still get a deterministic best estimate.
    """
    fixed = {"Burst Shot": 220, "Refulgent Arrow": 280,
             "Empyreal Arrow": 260, "Heartbreak Shot": 180}

    def normalized(event: dict[str, Any]) -> float:
        amount = float(event["amount"])
        timestamp = event.get("timestamp")
        unfed = isinstance(timestamp, (int, float)) and not food_active(timestamp, food_missing)
        if event.get("hitType") == 2:
            amount /= (
                unfed_critical_multiplier
                if unfed and unfed_critical_multiplier is not None else critical_multiplier
            )
        if event.get("directHit") is True:
            amount /= 1.25
        # FF Logs includes raid buffs, target debuffs, and a 1.05 Medicated
        # contribution in this combined value. The actual Dexterity factor
        # differs; remove that difference to compare with unpotted hits.
        multiplier = event.get("multiplier", 1.0)
        if isinstance(multiplier, (int, float)) and multiplier > 0:
            amount /= multiplier
            if _has_buff(event, potion_buff_id):
                amount *= 1.05 / potion_multiplier
        if unfed:
            amount *= unfed_determination_ratio
        return amount

    references: dict[Any, list[tuple[float, float]]] = defaultdict(list)
    for event in landed:
        potency = fixed.get(_event_name(event, names))
        if (potency is not None and isinstance(event.get("timestamp"), (int, float))
                and not event.get("overkill")):
            references[event.get("targetID")].append(
                (float(event["timestamp"]), normalized(event) / potency)
            )
    if not references:
        return {}, ()
    encore_coda, _, _ = _brd_coda(casts, names)
    all_references = [(target, time, value) for target, rows in references.items()
                      for time, value in rows]
    packets: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for event in landed:
        if _event_name(event, names) in {"Pitch Perfect", "Apex Arrow", "Radiant Encore"}:
            packets[(event.get("packetID"), event.get("abilityGameID"))].append(event)
    estimates: dict[int, tuple[float, bool, float]] = {}
    counts: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0.0, 0])
    outside_details: dict[str, list[BrdOutsideExpectedHit]] = defaultdict(list)
    apex_uses: list[BrdApexUseEstimate] = []
    pitch_uncertain_hits: list[BrdPitchHitEstimate] = []
    for packet, hits in packets.items():
        action = _event_name(hits[0], names)
        cast = next((cast for cast in casts if
                     (cast.get("packetID"), cast.get("abilityGameID")) == packet), None)
        immune = cast is not None and any(
            isinstance(event, dict)
            and event.get("type") == "damage"
            and event.get("hitType") == 10
            and event.get("abilityGameID") == packet[1]
            and (
                event.get("packetID") == packet[0]
                if event.get("packetID") is not None and packet[0] is not None
                else event.get("timestamp") == cast.get("timestamp")
            )
            for event in raw_damage
        )
        cast_timestamp = cast.get("timestamp") if cast is not None else None
        blast_after = action == "Apex Arrow" and cast is not None and isinstance(cast_timestamp, (int, float)) and any(
            _event_name(other, names) == "Blast Arrow"
            and other.get("sourceID") == cast.get("sourceID")
            and isinstance(other.get("timestamp"), (int, float))
            and 0 < other["timestamp"] - cast_timestamp <= 10000
            for other in casts
        )
        measured = []
        baselines: dict[int, float] = {}
        for hit in hits:
            hit_timestamp = float(hit.get("timestamp", 0))
            target = hit.get("targetID")
            same = sorted(
                references.get(target, []),
                key=lambda row: abs(row[0] - hit_timestamp),
            )
            if len(same) >= 3:
                baseline = median(value for _, value in same[:30])
                weak = False
            else:
                nearby = sorted(all_references, key=lambda row: (
                    row[0] != target,
                    abs(row[1] - hit_timestamp),
                ))[:20]
                baseline = median(value for _, _, value in nearby)
                weak = True
            measured.append((hit, normalized(hit) / baseline, weak))
            baselines[id(hit)] = baseline
        apex_candidates = (
            [float(140 + 7 * (gauge - 20))
             for gauge in range(80 if blast_after else 20, 101, 5)]
            if action == "Apex Arrow" else []
        )
        apex_choice = (
            min(
                apex_candidates,
                key=lambda candidate: sum(
                    (effective / candidate - 1) ** 2 * (0.5 if weak else 1.0)
                    for _, effective, weak in measured
                ),
            )
            if apex_candidates else None
        )
        if apex_choice is not None:
            plausible = tuple(
                int(20 + (candidate - 140) / 7)
                for candidate in apex_candidates
                if all(abs(effective / candidate - 1) <= 0.065 for _, effective, _ in measured)
            )
            cast_time = cast.get("timestamp") if cast is not None else None
            hit_time = hits[0].get("timestamp")
            timestamp = cast_time if isinstance(cast_time, (int, float)) else hit_time
            if isinstance(timestamp, (int, float)):
                apex_uses.append(BrdApexUseEstimate(
                    (timestamp - fight_start) / 1000,
                    len(measured),
                    int(20 + (apex_choice - 140) / 7),
                    plausible,
                    packet=packet,
                ))
        for hit, effective, weak in measured:
            factors = (1.0,)
            if action in {"Pitch Perfect", "Radiant Encore"}:
                if len(measured) > 1:
                    other_hit, other_value, _ = next(
                        row for row in measured if row[0] is not hit
                    )
                    ratio = (
                        normalized(hit) / normalized(other_hit)
                        if hit.get("buffs") == other_hit.get("buffs")
                        else effective / other_value
                    )
                    factors = (1.0,) if ratio > 1.45 else (0.5,) if ratio < 0.69 else (1.0, 0.5)
                else:
                    # A single landed hit is full potency unless a second
                    # target in the packet was immune to the same action.
                    factors = (1.0, 0.5) if immune else (1.0,)
                stack_potencies = (100, 220, 360) if action == "Pitch Perfect" else (700, 800, 1100)
                if action == "Radiant Encore" and packet in encore_coda:
                    stack_potencies = (stack_potencies[encore_coda[packet] - 1],)
                candidates = sorted({float(potency * factor)
                                     for potency in stack_potencies for factor in factors})
            else:
                candidates = apex_candidates
            nearest = sorted(candidates, key=lambda value: abs(effective / value - 1))
            chosen = apex_choice if apex_choice is not None else nearest[0]
            # Natural damage variance makes neighboring candidates indistinguishable.
            # Pitch Perfect uses the 94%-106% roll band plus 0.5% for the
            # estimated player baseline and the rounded FF Logs multiplier.
            tolerance = 0.065 if action == "Pitch Perfect" else 0.08
            known_coda = action == "Radiant Encore" and packet in encore_coda
            certain_falloff = known_coda and len(measured) > 1 and len(factors) == 1
            uncertain = (
                (weak and not (certain_falloff or (known_coda and len(candidates) == 1)))
                or (not known_coda and abs(effective / chosen - 1) > tolerance)
                or any(
                    abs(effective / alternative - 1) <= tolerance
                    for alternative in nearest if alternative != chosen
                )
            )
            alternative = next((value for value in nearest if value != chosen), None)
            difference = abs(chosen - alternative) if uncertain and alternative is not None else 0.0
            outside_expected = abs(effective / chosen - 1) > tolerance
            if action == "Pitch Perfect" and uncertain:
                def pitch_label(potency: float) -> str:
                    for stacks, base in enumerate((100, 220, 360), 1):
                        if potency == base:
                            return f"{stacks}-stack full hit"
                        if potency == base / 2:
                            return f"{stacks}-stack falloff hit"
                    raise ValueError(f"unknown Pitch Perfect potency {potency}")

                plausible = tuple(
                    pitch_label(candidate) for candidate in candidates
                    if abs(effective / candidate - 1) <= tolerance
                )
                timestamp = hit.get("timestamp")
                if isinstance(timestamp, (int, float)):
                    lower_bound = chosen * (1 - tolerance)
                    upper_bound = chosen * (1 + tolerance)
                    closest_bound = min(
                        (lower_bound, upper_bound), key=lambda bound: abs(effective - bound)
                    )
                    pitch_uncertain_hits.append(BrdPitchHitEstimate(
                        (timestamp - fight_start) / 1000,
                        pitch_label(chosen),
                        plausible,
                        outside_expected,
                        100 * abs(effective - closest_bound) / closest_bound,
                    ))
            estimates[id(hit)] = chosen, uncertain, difference
            counts[action][0] += 1
            counts[action][1] += int(uncertain)
            counts[action][2] += difference
            if action == "Pitch Perfect" and not hit.get("overkill") and outside_expected:
                counts[action][3] += 1
                outside_details[action].append(
                    BrdOutsideExpectedHit(
                        normalized_damage=normalized(hit),
                        potency=chosen,
                        lower_damage=baselines[id(hit)] * chosen * (1 - tolerance),
                        upper_damage=baselines[id(hit)] * chosen * (1 + tolerance),
                    )
                )
    return estimates, tuple(
        BrdPotencyEstimateSummary(
            name, int(row[0]), int(row[1]), row[2], int(row[3]),
            tuple(outside_details[name]),
            tuple(sorted(apex_uses, key=lambda use: use.seconds)) if name == "Apex Arrow" else (),
            tuple(sorted(pitch_uncertain_hits, key=lambda hit: hit.seconds))
            if name == "Pitch Perfect" else (),
        )
        for name, row in sorted(counts.items())
    )
