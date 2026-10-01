"""Estimate delay and comparable potency from landed auto-attacks."""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from statistics import median
from typing import Any

from .buffs import self_damage_multiplier
from .damage import landed_fraction
from .errors import AnalysisError
from .events import _has_buff
from .models import AutoAttackSummary
from .penalties import penalty_multiplier, revival_multiplier
from .profiles import _CombatProfile, _load_weapon_delays

_WEAPON_DELAY_MATCH_TOLERANCE = 0.05

def _is_auto_attack(event: dict[str, Any], name: str) -> bool:
    # These stable game ability IDs are represented as Attack (melee) and Shot
    # (physical ranged) in FF Logs. Names remain a fallback for fixtures and
    # reports whose master data lacks a game ID.
    return event.get("abilityGameID") in {7, 8} or name in {"Attack", "Shot"}


def _estimate_delay(intervals: list[float]) -> float:
    if not intervals:
        raise AnalysisError(
            "at least two landed auto-attacks are required to estimate weapon delay"
        )
    centre = median(intervals)
    deviations = [abs(value - centre) for value in intervals]
    mad = median(deviations)
    # A small floor retains normal FF Logs timestamp jitter when MAD is tiny.
    radius = max(0.03, 3 * mad)
    cluster = [value for value in intervals if abs(value - centre) <= radius]
    if not cluster:
        raise AnalysisError("could not identify a stable auto-attack interval cluster")
    return median(cluster)


def _match_weapon_delay(estimated: float, known: tuple[float, ...], job: str) -> float:
    matched = min(known, key=lambda value: abs(value - estimated))
    difference = abs(matched - estimated)
    # Audited BRD and MCH Shot spacing can exceed nominal delay by ~42 ms.
    # Match the nearest known delay, allowing up to 50 ms of timestamp variation.
    tolerance = _WEAPON_DELAY_MATCH_TOLERANCE
    if difference > tolerance:
        formatted = ", ".join(f"{value:.2f}" for value in known)
        raise AnalysisError(
            f"estimated auto-attack delay {estimated:.3f}s for {job} does not match "
            f"a known value within {tolerance:.2f}s ({formatted})"
        )
    return matched


def _summarize_auto_attacks(
    events: list[dict[str, Any]], job: str, combat_profile: _CombatProfile,
    self_windows: dict[int, tuple[tuple[int, int, float], ...]] | None = None,
    damage_penalties: dict[int, tuple[str, float]] | None = None,
) -> tuple[tuple[AutoAttackSummary, ...], float, float]:
    known_delays = _load_weapon_delays(job)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        name = str(event["_resolved_name"])
        grouped[name].append(event)

    summaries = []
    potted_base = potion_gain = 0.0
    for name, action_events in sorted(grouped.items()):
        timed = sorted(
            (event for event in action_events
             if isinstance(event.get("timestamp"), (int, float))),
            key=lambda event: event["timestamp"],
        )
        # Army's Paeon and Army's Muse change BRD's attack speed. Keep every
        # landed Shot in the potency total, but use only pairs whose endpoints
        # are free of either status to infer the underlying weapon delay.
        haste_statuses = (1002218, 1001932) if job.casefold() == "bard" else ()
        intervals = [
            (right["timestamp"] - left["timestamp"]) / 1000
            for left, right in pairwise(timed)
            if not any(_has_buff(event, status) for event in (left, right)
                       for status in haste_statuses)
        ]
        estimated_delay = _estimate_delay(intervals)
        weapon_delay = _match_weapon_delay(estimated_delay, known_delays, job)
        # Auto-attacks use the delay-adjusted weapon factor and do not receive
        # the action-damage trait. Express their damage as comparable action potency.
        normal_weapon_factor = (
            combat_profile.level_main * combat_profile.weapon_attribute_modifier // 1000
            + combat_profile.weapon_damage
        )
        auto_weapon_factor = int(normal_weapon_factor * weapon_delay / 3)
        potency_per_hit = (
            combat_profile.auto_base_potency
            * auto_weapon_factor
            / normal_weapon_factor
            * combat_profile.skill_speed_factor
            / combat_profile.action_trait_multiplier
        )
        base_total = action_gain = potted_effective = 0.0
        for event in action_events:
            base = potency_per_hit * landed_fraction(event) * (
                self_damage_multiplier(
                    str(event.get("buffs", "")),
                    float(event.get("_snapshot_time", event.get("timestamp", 0))), self_windows
                ) if self_windows else 1.0
            ) * penalty_multiplier(event, damage_penalties or {})
            effective_base = base * revival_multiplier(event, combat_profile)
            base_total += effective_base
            if _has_buff(event, combat_profile.potion_buff_id):
                unpotted_base = base * revival_multiplier(event, combat_profile, potted=False)
                potted_base += unpotted_base
                potted_effective += effective_base
                action_gain += (
                    effective_base * combat_profile.player_potion_multiplier - unpotted_base
                )
        # `base_total` uses the potted main-stat reduction on potted hits. Its
        # remaining potion factor must be added separately to the final total.
        potion_gain += action_gain
        summaries.append(
            AutoAttackSummary(
                name=name,
                hits=len(action_events),
                estimated_delay_seconds=estimated_delay,
                weapon_delay_seconds=weapon_delay,
                potency_per_hit=potency_per_hit,
                total_potency=base_total + potted_effective
                * (combat_profile.player_potion_multiplier - 1),
            )
        )
    return tuple(summaries), potted_base, potion_gain
