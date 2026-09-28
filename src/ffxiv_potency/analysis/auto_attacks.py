"""Estimate delay and comparable potency from landed auto-attacks."""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from statistics import median
from typing import Any

from .bard.buffs import _bard_self_multiplier
from .damage import landed_fraction
from .errors import AnalysisError
from .events import _has_buff
from .models import AutoAttackSummary
from .profiles import _CombatProfile, _load_weapon_delays

_WEAPON_DELAY_MATCH_TOLERANCE = 0.04

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
    if difference > _WEAPON_DELAY_MATCH_TOLERANCE:
        formatted = ", ".join(f"{value:.2f}" for value in known)
        raise AnalysisError(
            f"estimated auto-attack delay {estimated:.3f}s for {job} does not match "
            f"a known value within {_WEAPON_DELAY_MATCH_TOLERANCE:.2f}s ({formatted})"
        )
    return matched


def _summarize_auto_attacks(
    events: list[dict[str, Any]], job: str, combat_profile: _CombatProfile,
    self_windows: dict[int, tuple[tuple[int, int, float], ...]] | None = None,
) -> tuple[tuple[AutoAttackSummary, ...], float, float]:
    known_delays = _load_weapon_delays(job)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        name = str(event["_resolved_name"])
        grouped[name].append(event)

    summaries = []
    potted_base = potion_gain = 0.0
    for name, action_events in sorted(grouped.items()):
        values = sorted(
            float(event["timestamp"])
            for event in action_events
            if isinstance(event.get("timestamp"), (int, float))
        )
        intervals = [(right - left) / 1000 for left, right in pairwise(values)]
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
        buffed_bases = [
            potency_per_hit * landed_fraction(event) * (
                _bard_self_multiplier(
                    str(event.get("buffs", "")), float(event.get("timestamp", 0)), self_windows
                ) if self_windows else 1.0
            )
            for event in action_events
        ]
        base_total = sum(buffed_bases)
        potted_action_base = sum(
            base for event, base in zip(action_events, buffed_bases)
            if _has_buff(event, combat_profile.potion_buff_id)
        )
        action_gain = potted_action_base * (combat_profile.player_potion_multiplier - 1)
        potted_base += potted_action_base
        potion_gain += action_gain
        summaries.append(
            AutoAttackSummary(
                name=name,
                hits=len(action_events),
                estimated_delay_seconds=estimated_delay,
                weapon_delay_seconds=weapon_delay,
                potency_per_hit=potency_per_hit,
                total_potency=base_total + action_gain,
            )
        )
    return tuple(summaries), potted_base, potion_gain

