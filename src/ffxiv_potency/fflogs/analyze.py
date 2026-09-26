"""Turn saved FF Logs events into an auditable potency report."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from importlib.resources import files
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

from ..jobguide.snapshot import LATEST_KNOWN_PATCH
from .models import (
    ActionSummary,
    AnalysisResult,
    AutoAttackSummary,
    HitOutcomeSummary,
    PetDeploymentSummary,
    PotionSummary,
    PotionWindow,
)

_WEAPON_DELAY_MATCH_TOLERANCE = 0.04


class AnalysisError(ValueError):
    """Raised when saved log or action data cannot be analyzed safely."""


@dataclass(frozen=True, slots=True)
class _CombatProfile:
    potion_buff_id: int
    potion_action_names: tuple[str, ...]
    potion_duration_seconds: int
    player_potion_multiplier: float
    pet_potion_multipliers: dict[str, float]
    critical_damage_multiplier: float
    non_random_damage_actions: frozenset[str]
    auto_base_potency: int
    weapon_damage: int
    action_trait_multiplier: float
    weapon_attribute_modifier: int
    level_main: int
    skill_speed_factor: float
    critical_rate: float
    direct_rate: float


@dataclass(frozen=True, slots=True)
class _PetProfile:
    potency_multiplier: float
    gauge_name: str | None = None
    gauge_minimum: int | None = None
    gauge_maximum: int | None = None
    deployment_action: str | None = None


def _load_json(path: Path, expected: type) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"could not read {path}: {exc}") from exc
    if not isinstance(value, expected):
        raise AnalysisError(f"{path} must contain a JSON {expected.__name__}")
    return value


def _find_ranking_amount(
    value: Any, source_id: int | None, source_name: str | None
) -> float | None:
    if isinstance(value, dict):
        actor_id = value.get("id")
        actor_name = value.get("name")
        amount = value.get("amount")
        identity_matches = (source_id is not None and actor_id == source_id) or (
            source_name is not None
            and isinstance(actor_name, str)
            and actor_name.casefold() == source_name.casefold()
        )
        if identity_matches and isinstance(amount, (int, float)):
            return float(amount)
        for child in value.values():
            found = _find_ranking_amount(child, source_id, source_name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_ranking_amount(child, source_id, source_name)
            if found is not None:
                return found
    return None


def _event_name(event: dict[str, Any], ability_names: dict[int, str]) -> str:
    game_id = event.get("abilityGameID")
    if not isinstance(game_id, int):
        return f"Unknown ability {game_id}"
    return ability_names.get(game_id, f"Unknown ability {game_id}")


def _summarize_hit_outcomes(events: list[dict[str, Any]]) -> HitOutcomeSummary:
    normal = critical = direct = critical_direct = unknown = 0
    for event in events:
        hit_type = event.get("hitType")
        if not isinstance(hit_type, int):
            unknown += 1
            continue
        is_critical = hit_type == 2
        is_direct = event.get("directHit") is True
        if is_critical and is_direct:
            critical_direct += 1
        elif is_critical:
            critical += 1
        elif is_direct:
            direct += 1
        else:
            normal += 1
    return HitOutcomeSummary(normal, critical, direct, critical_direct, unknown)


def _luck_contribution(event: dict[str, Any], critical_multiplier: float) -> float | None:
    """Return the damage bonus represented by one random hit outcome."""
    hit_type = event.get("hitType")
    if not isinstance(hit_type, int):
        return None
    multiplier = critical_multiplier if hit_type == 2 else 1.0
    if event.get("directHit") is True:
        multiplier *= 1.25
    return multiplier - 1.0


def _guaranteed_outcome_packets(
    casts: list[dict[str, Any]],
    actions: dict[str, dict[str, Any]],
    ability_names: dict[int, str],
) -> set[tuple[Any, Any]]:
    """Find weaponskill packets whose CDH outcome was forced by an earlier cast."""
    guaranteed: set[tuple[Any, Any]] = set()
    for index, cast in enumerate(casts):
        action = actions.get(_event_name(cast, ability_names), {})
        description = " ".join(action.get("description", ())).casefold()
        if "guarantees that next weaponskill is a critical direct hit" not in description:
            continue
        for candidate in casts[index + 1 :]:
            candidate_action = actions.get(_event_name(candidate, ability_names), {})
            action_type = candidate_action.get("type")
            if isinstance(action_type, str) and "weaponskill" in action_type.casefold():
                if candidate.get("packetID") is not None:
                    guaranteed.add((candidate.get("packetID"), candidate.get("abilityGameID")))
                break
    return guaranteed


def _has_inherently_guaranteed_outcome(action: dict[str, Any]) -> bool:
    description = " ".join(action.get("description", ())).casefold()
    return "delivers a critical direct hit" in description


def _is_channeled_action(action: dict[str, Any]) -> bool:
    description = " ".join(action.get("description", ())).casefold()
    return "effect ends upon using another action or moving" in description


def _is_auto_attack(event: dict[str, Any], name: str) -> bool:
    # These stable game ability IDs are represented as Attack (melee) and Shot
    # (physical ranged) in FF Logs. Names remain a fallback for fixtures and
    # reports whose master data lacks a game ID.
    return event.get("abilityGameID") in {7, 8} or name in {"Attack", "Shot"}


def _load_weapon_delays(job: str) -> tuple[float, ...]:
    resource = files("ffxiv_potency").joinpath("data/weapon_delays.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    values = document.get("jobs", {}).get(job.lower())
    if not isinstance(values, list) or not values:
        raise AnalysisError(f"no known weapon delays are configured for job {job!r}")
    if not all(isinstance(value, (int, float)) and value > 0 for value in values):
        raise AnalysisError(f"invalid weapon-delay configuration for job {job!r}")
    return tuple(float(value) for value in values)


def _load_pet_profiles(job: str) -> dict[str, _PetProfile]:
    resource = files("ffxiv_potency").joinpath("data/pet_scaling.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    job_profile = document.get("jobs", {}).get(job.lower())
    if job_profile is None:
        return {}
    if not isinstance(job_profile, dict):
        raise AnalysisError(f"invalid pet-scaling configuration for job {job!r}")
    pets = job_profile.get("pets", {})
    if not isinstance(pets, dict):
        raise AnalysisError(f"invalid pet profiles for job {job!r}")

    profiles: dict[str, _PetProfile] = {}
    for pet_name, profile in pets.items():
        multiplier = profile.get("potency_multiplier") if isinstance(profile, dict) else None
        if (
            not isinstance(pet_name, str)
            or not isinstance(multiplier, (int, float))
            or multiplier <= 0
        ):
            raise AnalysisError(f"invalid pet potency multiplier for job {job!r}")
        gauge = profile.get("gauge")
        if gauge is None:
            profiles[pet_name] = _PetProfile(float(multiplier))
            continue
        if not isinstance(gauge, dict):
            raise AnalysisError(f"invalid pet gauge profile for {pet_name!r}")
        name = gauge.get("name")
        minimum = gauge.get("minimum")
        maximum = gauge.get("maximum")
        deployment = gauge.get("deployment_action")
        if not (
            isinstance(name, str)
            and isinstance(minimum, int)
            and isinstance(maximum, int)
            and 0 < minimum <= maximum
            and isinstance(deployment, str)
        ):
            raise AnalysisError(f"invalid pet gauge profile for {pet_name!r}")
        profiles[pet_name] = _PetProfile(float(multiplier), name, minimum, maximum, deployment)
    return profiles


def _main_stat_factor(
    dexterity: int,
    attribute_modifier: int,
    *,
    level_main: int,
    level_divisor: int,
    coefficient: int,
) -> int:
    modified = dexterity * attribute_modifier // 100
    return coefficient * (modified - level_main) // level_divisor + 100


def _critical_damage_multiplier(critical_hit: int, level_sub: int, level_divisor: int) -> float:
    """Calculate tiered critical-hit strength for the configured level."""
    return (1400 + 200 * (critical_hit - level_sub) // level_divisor) / 1000


def _load_combat_profile(job: str) -> _CombatProfile:
    resource = files("ffxiv_potency").joinpath("data/combat_profiles.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    profile = document.get("jobs", {}).get(job.lower())
    if not isinstance(profile, dict):
        raise AnalysisError(f"no combat profile is configured for job {job!r}")
    dexterity = profile.get("dexterity", {})
    stats = profile.get("secondary_stats", {})
    modifiers = profile.get("attribute_modifiers", {})
    potion = profile.get("potion", {})
    luck = profile.get("luck", {})
    required_ints = {
        "level_main": profile.get("level_main"),
        "level_sub": profile.get("level_sub"),
        "level_divisor": profile.get("level_divisor"),
        "coefficient": profile.get("attack_power_coefficient"),
        "solo": dexterity.get("solo_unpotted"),
        "party": dexterity.get("party_unpotted"),
        "potted": dexterity.get("party_potted"),
        "player_modifier": modifiers.get("player"),
        "potion_cap": potion.get("cap"),
        "buff_id": potion.get("buff_id"),
        "potion_duration": potion.get("duration_seconds"),
        "critical_hit": stats.get("critical_hit"),
        "direct_hit": stats.get("direct_hit"),
        "auto_base_potency": profile.get("auto_attack", {}).get("base_potency"),
        "weapon_damage": profile.get("auto_attack", {}).get("weapon_damage"),
        "skill_speed": stats.get("skill_speed"),
    }
    if not all(isinstance(value, int) and value > 0 for value in required_ints.values()):
        raise AnalysisError(f"invalid combat profile for job {job!r}")
    auto_profile = profile["auto_attack"]
    trait_multiplier = auto_profile.get("action_trait_multiplier")
    if not isinstance(trait_multiplier, (int, float)) or trait_multiplier <= 0:
        raise AnalysisError(f"invalid auto-attack trait multiplier for job {job!r}")
    action_names = potion.get("action_names")
    if not isinstance(action_names, list) or not all(
        isinstance(name, str) for name in action_names
    ):
        raise AnalysisError(f"invalid potion action names for job {job!r}")
    non_random_actions = luck.get("non_random_damage_actions")
    if not isinstance(non_random_actions, list) or not all(
        isinstance(name, str) for name in non_random_actions
    ):
        raise AnalysisError(f"invalid non-random damage actions for job {job!r}")

    factor_args = {
        "level_main": required_ints["level_main"],
        "level_divisor": required_ints["level_divisor"],
        "coefficient": required_ints["coefficient"],
    }
    player_before = _main_stat_factor(
        required_ints["party"], required_ints["player_modifier"], **factor_args
    )
    player_after = _main_stat_factor(
        required_ints["potted"], required_ints["player_modifier"], **factor_args
    )
    pet_multipliers = {}
    for actor, modifier in modifiers.items():
        if actor == "player":
            continue
        if not isinstance(modifier, int) or modifier <= 0:
            raise AnalysisError(f"invalid attribute modifier for {actor!r}")
        pet_before = _main_stat_factor(required_ints["solo"], modifier, **factor_args)
        pet_after = _main_stat_factor(
            required_ints["solo"] + required_ints["potion_cap"], modifier, **factor_args
        )
        pet_multipliers[actor] = pet_after / pet_before
    return _CombatProfile(
        potion_buff_id=required_ints["buff_id"],
        potion_action_names=tuple(action_names),
        potion_duration_seconds=required_ints["potion_duration"],
        player_potion_multiplier=player_after / player_before,
        pet_potion_multipliers=pet_multipliers,
        critical_damage_multiplier=_critical_damage_multiplier(
            required_ints["critical_hit"],
            required_ints["level_sub"],
            required_ints["level_divisor"],
        ),
        non_random_damage_actions=frozenset(non_random_actions),
        auto_base_potency=required_ints["auto_base_potency"],
        weapon_damage=required_ints["weapon_damage"],
        action_trait_multiplier=float(trait_multiplier),
        weapon_attribute_modifier=required_ints["player_modifier"],
        level_main=required_ints["level_main"],
        skill_speed_factor=(
            1000
            + 130
            * (required_ints["skill_speed"] - required_ints["level_sub"])
            // required_ints["level_divisor"]
        )
        / 1000,
        critical_rate=(
            50
            + 200
            * (required_ints["critical_hit"] - required_ints["level_sub"])
            // required_ints["level_divisor"]
        )
        / 1000,
        direct_rate=(
            550
            * (required_ints["direct_hit"] - required_ints["level_sub"])
            // required_ints["level_divisor"]
        )
        / 1000,
    )


def _has_buff(event: dict[str, Any], buff_id: int) -> bool:
    buffs = event.get("buffs")
    return isinstance(buffs, str) and str(buff_id) in buffs.split(".")


def _load_raid_effects(actions_path: Path) -> list[dict[str, Any]]:
    """Use the refreshed guide snapshot for the action patch when available."""
    bundled = files("ffxiv_potency").joinpath("data/raid_effects.json")
    patch = _load_json(actions_path, dict).get("patch")
    candidate = actions_path.parent.parent.parent / "raid_buffs" / str(patch) / "effects.json"
    document = (
        _load_json(candidate, dict)
        if candidate.is_file()
        else json.loads(bundled.read_text(encoding="utf-8"))
    )
    if patch is not None and document.get("patch") != patch:
        raise AnalysisError(
            f"raid-effect data for patch {patch!r} is missing; run 'ffxiv-potency jobguide buffs'"
        )
    effects = document.get("effects")
    if not isinstance(effects, list) or len(effects) != 5:
        raise AnalysisError("raid-effect snapshot must contain all five configured crit/DH effects")
    return effects


def _raid_luck_adjustment(
    event: dict[str, Any],
    effects: list[dict[str, Any]],
    ability_names: dict[int, str],
    profile: _CombatProfile,
) -> float:
    """Expected extra damage bonus caused by raid crit/DH rate buffs."""
    crit_bonus = direct_bonus = 0.0
    for effect in effects:
        status = str(effect["status"]).removeprefix("The ")
        active = any(
            _has_buff(event, game_id)
            for game_id, name in ability_names.items()
            if name.removeprefix("The ") == status
        )
        if active:
            if effect["rate"] == "critical":
                crit_bonus += float(effect["bonus"])
            else:
                direct_bonus += float(effect["bonus"])
    strength = profile.critical_damage_multiplier - 1
    before = (1 + profile.critical_rate * strength) * (1 + profile.direct_rate * 0.25)
    after = (1 + min(1.0, profile.critical_rate + crit_bonus) * strength) * (
        1 + min(1.0, profile.direct_rate + direct_bonus) * 0.25
    )
    return after - before


def _potion_windows(
    casts: list[dict[str, Any]],
    landed: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    ability_names: dict[int, str],
    profile: _CombatProfile,
    fight_start: float,
    fight_end: float,
    source_id: int | None,
) -> tuple[PotionWindow, ...]:
    """Recover pre-pull potion windows using removal events when available."""
    cast_times = [
        cast.get("timestamp")
        for cast in casts
        if _event_name(cast, ability_names) in profile.potion_action_names
    ]
    cast_times = sorted(time for time in cast_times if isinstance(time, (int, float)))
    duration_ms = profile.potion_duration_seconds * 1000
    removals = sorted(
        event["timestamp"]
        for event in buffs
        if event.get("type") in ("removebuff", "removebuffstack")
        and event.get("abilityGameID")
        in (profile.potion_buff_id, profile.potion_buff_id % 1_000_000)
        and event.get("targetID") == source_id
        and isinstance(event.get("timestamp"), (int, float))
    )
    potted_times = sorted(
        event["timestamp"]
        for event in landed
        if _has_buff(event, profile.potion_buff_id)
        and isinstance(event.get("timestamp"), (int, float))
    )
    clusters: list[list[float]] = []
    for timestamp in potted_times:
        if not clusters or timestamp - clusters[-1][0] >= duration_ms:
            clusters.append([])
        clusters[-1].append(timestamp)
    windows = []
    for cast in cast_times:
        # The cast can precede buff application; a self-removal records the
        # observed end more accurately than cast time plus the nominal duration.
        removal = next(
            (time for time in removals if cast <= time <= cast + duration_ms + 3000),
            None,
        )
        end = removal if removal is not None else cast + duration_ms
        windows.append(
            PotionWindow(
                (cast - fight_start) / 1000,
                (min(fight_end, end) - fight_start) / 1000,
            )
        )
    for cluster in clusters:
        first, last = cluster[0], cluster[-1]
        # Snapshot damage can land after the buff expires; it is still part of
        # the original potion window, including when the damage forms a new cluster.
        if any(0 <= first - cast <= duration_ms + 3000 for cast in cast_times):
            continue
        if any(0 <= first - time <= 3000 for time in removals):
            continue
        # A damage event can retain its snapshot buff just after removal.
        removal = next(
            (
                time
                for time in removals
                if first <= time <= first + duration_ms and last <= time + 2000
            ),
            None,
        )
        start = removal - duration_ms if removal is not None else None
        windows.append(
            PotionWindow(
                (start - fight_start) / 1000 if start is not None else None,
                (removal - fight_start) / 1000 if removal is not None else None,
                (first - fight_start) / 1000,
                (last - fight_start) / 1000,
                inferred=True,
            )
        )
    return tuple(
        sorted(
            windows,
            key=lambda window: (
                window.start_seconds
                if window.start_seconds is not None
                else window.observed_start_seconds or 0
            ),
        )
    )


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
    events: list[dict[str, Any]], job: str, combat_profile: _CombatProfile
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
        potted_hits = sum(
            _has_buff(event, combat_profile.potion_buff_id) for event in action_events
        )
        base_total = potency_per_hit * len(action_events)
        potted_action_base = potency_per_hit * potted_hits
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


def _reconstruct_pet_deployments(
    casts: list[dict[str, Any]],
    actions: dict[str, dict[str, Any]],
    ability_names: dict[int, str],
    landed_by_packet: dict[tuple[Any, Any], list[dict[str, Any]]],
    profiles: dict[str, _PetProfile],
    fight_start: float,
) -> tuple[PetDeploymentSummary, ...]:
    gauge_values: dict[str, int] = defaultdict(int)
    deployments: list[PetDeploymentSummary] = []
    deployment_profiles = {
        profile.deployment_action: (actor, profile)
        for actor, profile in profiles.items()
        if profile.deployment_action is not None
    }

    for cast in casts:
        action_name = _event_name(cast, ability_names)
        action = actions.get(action_name, {})
        packet = (cast.get("packetID"), cast.get("abilityGameID"))
        landed_events = landed_by_packet.get(packet, [])
        for gain in action.get("gauge_gains", []):
            if not isinstance(gain, dict) or not landed_events:
                continue
            gauge_name = gain.get("gauge")
            amount = gain.get("amount")
            requires_combo = gain.get("requires_combo") is True
            if not isinstance(gauge_name, str) or not isinstance(amount, int):
                continue
            if requires_combo and not any(e.get("bonusPercent") is not None for e in landed_events):
                continue
            configured_maxima = [
                profile.gauge_maximum
                for profile in profiles.values()
                if profile.gauge_name == gauge_name and profile.gauge_maximum is not None
            ]
            maximum = max(configured_maxima, default=100)
            gauge_values[gauge_name] = min(maximum, gauge_values[gauge_name] + amount)

        deployment_entry = deployment_profiles.get(action_name)
        if deployment_entry is None:
            continue
        actor, profile = deployment_entry
        assert profile.gauge_name is not None
        spent = gauge_values[profile.gauge_name]
        if profile.gauge_minimum is not None and spent < profile.gauge_minimum:
            raise AnalysisError(
                f"reconstructed only {spent} {profile.gauge_name} at {action_name} deployment"
            )
        timestamp = cast.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            raise AnalysisError(f"{action_name} deployment has no timestamp")
        deployments.append(
            PetDeploymentSummary(
                actor=actor,
                timestamp_seconds=(timestamp - fight_start) / 1000,
                gauge=profile.gauge_name,
                gauge_spent=spent,
            )
        )
        gauge_values[profile.gauge_name] = 0
    return tuple(deployments)


def _deployment_for_event(
    actor: str, timestamp: Any, deployments: tuple[PetDeploymentSummary, ...], fight_start: float
) -> PetDeploymentSummary | None:
    if not isinstance(timestamp, (int, float)):
        return None
    relative = (timestamp - fight_start) / 1000
    candidates = [
        deployment
        for deployment in deployments
        if deployment.actor == actor and deployment.timestamp_seconds <= relative
    ]
    return candidates[-1] if candidates else None


def _direct_potency(
    action: dict[str, Any],
    event: dict[str, Any],
    *,
    is_primary_target: bool,
    modifier_bonus: int = 0,
    source_multiplier: float = 1.0,
    gauge_spent: int | None = None,
    gauge_minimum: int | None = None,
    gauge_maximum: int | None = None,
) -> tuple[float, float] | None:
    potency = action.get("potency")
    if not isinstance(potency, dict):
        return None

    if event.get("tick"):
        dot = potency.get("damage_over_time")
        if isinstance(dot, dict) and isinstance(dot.get("potency_per_tick"), int):
            value = float(dot["potency_per_tick"])
            return value * source_multiplier, value * source_multiplier
        triggered = potency.get("triggered")
        if isinstance(triggered, dict):
            # Triggered actions such as Wildfire are resolved separately.
            return None

    value = potency.get("base")
    combo = potency.get("combo")
    if event.get("bonusPercent") is not None and isinstance(combo, dict):
        value = combo.get("potency", value)
    if not isinstance(value, int):
        return None

    minimum = maximum = float(value + modifier_bonus)
    scaling = potency.get("gauge_scaling")
    if isinstance(scaling, dict) and isinstance(scaling.get("maximum_potency"), int):
        scaling_maximum = float(scaling["maximum_potency"])
        if (
            gauge_spent is not None
            and gauge_minimum is not None
            and gauge_maximum is not None
            and gauge_maximum > gauge_minimum
        ):
            progress = (gauge_spent - gauge_minimum) / (gauge_maximum - gauge_minimum)
            minimum = maximum = minimum + (scaling_maximum - minimum) * progress
        else:
            maximum = scaling_maximum

    falloff = potency.get("falloff")
    if not is_primary_target and isinstance(falloff, dict):
        multiplier = falloff.get("additional_target_multiplier")
        if isinstance(multiplier, (int, float)):
            minimum *= multiplier
            maximum *= multiplier
    return minimum * source_multiplier, maximum * source_multiplier


def analyze_saved_fight(directory: Path, actions_path: Path) -> AnalysisResult:
    """Analyze one directory produced by :func:`download_report_events`.

    FF Logs returns both ``calculateddamage`` and the later authoritative
    ``damage`` record for many packets. Only the latter is considered landed.
    """

    fight = _load_json(directory / "fight.json", dict)
    master_data = _load_json(directory / "master-data.json", dict)
    raw_damage = _load_json(directory / "damage-events.json", list)
    casts = _load_json(directory / "cast-events.json", list)
    buffs_path = directory / "buff-events.json"
    buffs = _load_json(buffs_path, list) if buffs_path.is_file() else []
    action_document = _load_json(actions_path, dict)
    snapshot_patch = action_document.get("patch")
    if snapshot_patch is not None and snapshot_patch != LATEST_KNOWN_PATCH:
        raise AnalysisError(
            f"only patch {LATEST_KNOWN_PATCH} actions are supported for now; "
            f"received {snapshot_patch!r}"
        )

    start = fight.get("startTime")
    end = fight.get("endTime")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
        raise AnalysisError("fight.json contains an invalid time range")
    duration = (end - start) / 1000

    abilities = master_data.get("abilities")
    if not isinstance(abilities, list):
        raise AnalysisError("master-data.json is missing abilities")
    ability_names = {
        item["gameID"]: item["name"]
        for item in abilities
        if isinstance(item, dict)
        and isinstance(item.get("gameID"), int)
        and isinstance(item.get("name"), str)
    }
    actors_value = master_data.get("actors", [])
    actors = {
        item["id"]: item
        for item in actors_value
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    actions_value = action_document.get("actions")
    if not isinstance(actions_value, list):
        raise AnalysisError(f"{actions_path} is missing actions")
    actions = {
        item["name"]: item
        for item in actions_value
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    job = action_document.get("job")
    if not isinstance(job, str) or not job:
        raise AnalysisError(f"{actions_path} is missing job")
    pet_profiles = _load_pet_profiles(job)
    combat_profile = _load_combat_profile(job)
    raid_effects = _load_raid_effects(actions_path)

    # FF Logs emits zero-amount damage rows for immune targets (hitType 10),
    # sometimes alongside a positive hit on another target from the same cast.
    landed = [
        event
        for event in raw_damage
        if isinstance(event, dict)
        and event.get("type") == "damage"
        and event.get("hitType") != 10
        and event.get("amount") != 0
    ]
    landed_by_packet: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for event in landed:
        if event.get("packetID") is not None:
            landed_by_packet[(event.get("packetID"), event.get("abilityGameID"))].append(event)
    landed_packets = set(landed_by_packet)

    # A selected target may differ from the first enemy hit by a travelling
    # attack. For aggregate potency, any one landed hit can take full potency.
    # Prefer the selected target if it took damage; otherwise use the first
    # landed hit. Per-target attribution will require more information.
    selected_targets = {
        (event.get("packetID"), event.get("abilityGameID")): event.get("targetID")
        for event in casts
        if isinstance(event, dict) and event.get("packetID") is not None
    }
    primary_hits = {
        packet: next(
            (hit for hit in hits if hit.get("targetID") == selected_targets.get(packet)),
            hits[0],
        )
        if selected_targets.get(packet) is not None
        else hits[0]
        for packet, hits in landed_by_packet.items()
    }

    totals: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    pet_totals: dict[PetDeploymentSummary, list[float]] = defaultdict(lambda: [0.0, 0.0])
    pet_landed_actions: dict[PetDeploymentSummary, set[str]] = defaultdict(set)
    use_keys: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
    unmatched: dict[str, int] = defaultdict(int)
    auto_attack_events: list[dict[str, Any]] = []
    matched_events = 0
    potted_min = potted_max = potion_gain_min = potion_gain_max = 0.0
    luck_weighted_bonus = luck_weighted_maximum = luck_weighted_raid_adjustment = 0.0

    def record_luck(event: dict[str, Any], potency_weight: float) -> None:
        """Accumulate the same weighted outcome for actions, pets, and auto-attacks."""
        nonlocal luck_weighted_bonus, luck_weighted_maximum, luck_weighted_raid_adjustment
        contribution = _luck_contribution(event, combat_profile.critical_damage_multiplier)
        if contribution is None:
            return
        luck_weighted_bonus += potency_weight * contribution
        luck_weighted_raid_adjustment += potency_weight * _raid_luck_adjustment(
            event, raid_effects, ability_names, combat_profile
        )
        luck_weighted_maximum += potency_weight * (
            combat_profile.critical_damage_multiplier * 1.25 - 1
        )

    # Resolve triggered potency from landed weaponskills between its cast and
    # delayed damage event. This models Wildfire without using damage values.
    sorted_casts = sorted(
        (e for e in casts if isinstance(e, dict)), key=lambda e: e.get("timestamp", 0)
    )
    player_source_counts = Counter(
        event.get("sourceID")
        for event in sorted_casts
        if actors.get(event.get("sourceID"), {}).get("type") == "Player"
    )
    source_id = player_source_counts.most_common(1)[0][0] if player_source_counts else None
    source_name = actors.get(source_id, {}).get("name", f"Source {source_id}")
    rankings_path = directory / "rankings.json"
    rankings = _load_json(rankings_path, dict) if rankings_path.is_file() else {}
    ndps = (
        _find_ranking_amount(rankings.get("rankings"), source_id, str(source_name))
        if rankings.get("metric") == "ndps"
        else None
    )
    rdps = (
        _find_ranking_amount(rankings.get("rdps"), source_id, str(source_name))
        if rankings.get("metric") == "ndps"
        else None
    )
    potion_windows = _potion_windows(
        sorted_casts,
        landed,
        buffs,
        ability_names,
        combat_profile,
        float(start),
        float(end),
        source_id,
    )
    pet_deployments = _reconstruct_pet_deployments(
        sorted_casts, actions, ability_names, landed_by_packet, pet_profiles, float(start)
    )
    guaranteed_packets = _guaranteed_outcome_packets(sorted_casts, actions, ability_names)
    channel_casts: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for cast_index, cast in enumerate(sorted_casts):
        cast_name = _event_name(cast, ability_names)
        if _is_channeled_action(actions.get(cast_name, {})):
            channel_casts[cast_name].append((cast_index, cast))

    # Map temporary flat potency modifiers (currently Hypercharge) to the
    # packets that consume them. Uses are consumed by qualifying casts even if
    # they later ghost, while only landed packets contribute potency below.
    modifier_bonuses: dict[tuple[Any, Any], int] = defaultdict(int)
    for index, modifier_cast in enumerate(sorted_casts):
        modifier_action = actions.get(_event_name(modifier_cast, ability_names), {})
        modifier_potency = modifier_action.get("potency")
        modifier = modifier_potency.get("modifier") if isinstance(modifier_potency, dict) else None
        if not isinstance(modifier, dict):
            continue
        bonus = modifier.get("bonus")
        maximum_uses = modifier.get("maximum_uses")
        if not isinstance(bonus, int) or not isinstance(maximum_uses, int):
            continue
        used = 0
        for candidate in sorted_casts[index + 1 :]:
            candidate_name = _event_name(candidate, ability_names)
            if candidate_name == _event_name(modifier_cast, ability_names):
                break
            candidate_action = actions.get(candidate_name, {})
            candidate_potency = candidate_action.get("potency")
            action_type = candidate_action.get("type", "")
            is_single_target_weaponskill = (
                isinstance(action_type, str)
                and "weaponskill" in action_type.lower()
                and isinstance(candidate_potency, dict)
                and candidate_potency.get("falloff") is None
            )
            if not is_single_target_weaponskill:
                continue
            packet = (candidate.get("packetID"), candidate.get("abilityGameID"))
            if candidate.get("packetID") is not None:
                modifier_bonuses[packet] += bonus
            used += 1
            if used == maximum_uses:
                break

    for event in landed:
        name = _event_name(event, ability_names)
        if _is_auto_attack(event, name):
            auto_attack_events.append({**event, "_resolved_name": name})
            continue
        action = actions.get(name)
        if action is None:
            unmatched[name] += 1
            continue

        source_actor = action.get("source_actor")
        profile = pet_profiles.get(source_actor) if isinstance(source_actor, str) else None
        deployment = (
            _deployment_for_event(
                source_actor, event.get("timestamp"), pet_deployments, float(start)
            )
            if isinstance(source_actor, str) and profile is not None
            else None
        )

        potency = action.get("potency")
        triggered = potency.get("triggered") if isinstance(potency, dict) else None
        values: tuple[float, float] | None = None
        if event.get("tick") and isinstance(triggered, dict):
            event_time = event.get("timestamp", 0)
            trigger_casts = [
                cast
                for cast in sorted_casts
                if _event_name(cast, ability_names) == name
                and cast.get("timestamp", 0) <= event_time
            ]
            if trigger_casts:
                started = trigger_casts[-1].get("timestamp", 0)
                maximum_triggers = triggered.get("maximum_triggers")
                potency_per_trigger = triggered.get("potency_per_trigger")
                qualifying = {
                    cast.get("packetID")
                    for cast in sorted_casts
                    if started < cast.get("timestamp", 0) <= event_time
                    and cast.get("packetID") is not None
                    and (cast.get("packetID"), cast.get("abilityGameID")) in landed_packets
                    and isinstance(
                        actions.get(_event_name(cast, ability_names), {}).get("type"), str
                    )
                    and "weaponskill" in actions[_event_name(cast, ability_names)]["type"].lower()
                }
                if isinstance(maximum_triggers, int) and isinstance(potency_per_trigger, int):
                    value = float(min(len(qualifying), maximum_triggers) * potency_per_trigger)
                    values = value, value
        if values is None:
            key = (event.get("packetID"), event.get("abilityGameID"))
            values = _direct_potency(
                action,
                event,
                is_primary_target=event.get("packetID") is None or event is primary_hits.get(key),
                modifier_bonus=modifier_bonuses.get(key, 0),
                source_multiplier=profile.potency_multiplier if profile is not None else 1.0,
                gauge_spent=deployment.gauge_spent if deployment is not None else None,
                gauge_minimum=profile.gauge_minimum if profile is not None else None,
                gauge_maximum=profile.gauge_maximum if profile is not None else None,
            )
        if values is None:
            unmatched[name] += 1
            continue

        if _has_buff(event, combat_profile.potion_buff_id):
            potion_multiplier = (
                combat_profile.pet_potion_multipliers.get(
                    source_actor, combat_profile.player_potion_multiplier
                )
                if isinstance(source_actor, str)
                else combat_profile.player_potion_multiplier
            )
            potted_min += values[0]
            potted_max += values[1]
            potion_gain_min += values[0] * (potion_multiplier - 1)
            potion_gain_max += values[1] * (potion_multiplier - 1)
            values = values[0] * potion_multiplier, values[1] * potion_multiplier

        if deployment is not None:
            pet_row = pet_totals[deployment]
            pet_row[0] += values[0]
            pet_row[1] += values[1]
            pet_landed_actions[deployment].add(name)

        key = (event.get("packetID"), event.get("abilityGameID"))
        is_random_outcome = (
            key not in guaranteed_packets
            and name not in combat_profile.non_random_damage_actions
            and not _has_inherently_guaranteed_outcome(action)
        )
        if is_random_outcome:
            record_luck(event, sum(values) / 2)

        matched_events += 1
        row = totals[name]
        row[0] += 1
        row[1] += values[0]
        row[2] += values[1]
        packet_id = event.get("packetID")
        use_key = (
            (
                packet_id,
                event.get("abilityGameID"),
                event.get("timestamp") if event.get("tick") else None,
            )
            if packet_id is not None
            else ("event", id(event))
        )
        use_keys[name].add(use_key)

    ghosted: dict[str, int] = defaultdict(int)
    ghosted_times: dict[str, list[float]] = defaultdict(list)

    def record_ghost(name: str, cast: dict[str, Any]) -> None:
        ghosted[name] += 1
        timestamp = cast.get("timestamp")
        if isinstance(timestamp, (int, float)):
            ghosted_times[name].append((timestamp - start) / 1000)

    for name, channel_uses in channel_casts.items():
        for cast_index, cast in channel_uses:
            next_action = next(
                (
                    candidate.get("timestamp")
                    for candidate in sorted_casts[cast_index + 1 :]
                    if candidate.get("sourceID") == cast.get("sourceID")
                ),
                end,
            )
            if not isinstance(next_action, (int, float)):
                continue
            if not any(
                _event_name(hit, ability_names) == name
                and hit.get("sourceID") == cast.get("sourceID")
                and isinstance(hit.get("timestamp"), (int, float))
                and cast.get("timestamp", start) <= hit["timestamp"] < next_action
                for hit in landed
            ):
                record_ghost(name, cast)
    for cast in sorted_casts:
        name = _event_name(cast, ability_names)
        if name in channel_casts:
            continue
        action = actions.get(name)
        potency = action.get("potency") if action else None
        if not isinstance(potency, dict) or not isinstance(potency.get("base"), int):
            continue
        packet = (cast.get("packetID"), cast.get("abilityGameID"))
        if cast.get("packetID") is not None and packet not in landed_packets:
            record_ghost(name, cast)

    summaries = tuple(
        ActionSummary(
            name,
            int(values[0]),
            values[1],
            values[2],
            uses=len(channel_casts[name]) if name in channel_casts else len(use_keys[name]),
        )
        for name, values in sorted(totals.items(), key=lambda item: (-item[1][1], item[0]))
    )
    if auto_attack_events:
        auto_attacks, auto_potted, auto_gain = _summarize_auto_attacks(
            auto_attack_events, job, combat_profile
        )
        potted_min += auto_potted
        potted_max += auto_potted
        potion_gain_min += auto_gain
        potion_gain_max += auto_gain
    else:
        auto_attacks = ()
    auto_attack_potency = sum(item.total_potency for item in auto_attacks)
    if auto_attack_events:
        auto_potency_by_name = {item.name: item.potency_per_hit for item in auto_attacks}
        for event in auto_attack_events:
            potency_weight = auto_potency_by_name[str(event["_resolved_name"])]
            if _has_buff(event, combat_profile.potion_buff_id):
                potency_weight *= combat_profile.player_potion_multiplier
            record_luck(event, potency_weight)
    gear_baseline = (
        (1 + combat_profile.critical_rate * (combat_profile.critical_damage_multiplier - 1))
        * (1 + combat_profile.direct_rate * 0.25)
        - 1
    ) / (combat_profile.critical_damage_multiplier * 1.25 - 1)
    return AnalysisResult(
        fight_name=str(fight.get("name", "Unknown fight")),
        encounter_id=fight.get("encounterID")
        if isinstance(fight.get("encounterID"), int)
        else None,
        source_name=str(source_name),
        ndps=ndps,
        rdps=rdps,
        duration_seconds=duration,
        raw_damage_events=len(raw_damage),
        landed_damage_events=len(landed),
        matched_damage_events=matched_events,
        potency_min=sum(item.potency_min for item in summaries) + auto_attack_potency,
        potency_max=sum(item.potency_max for item in summaries) + auto_attack_potency,
        actions=summaries,
        auto_attacks=auto_attacks,
        pet_deployments=tuple(
            replace(
                deployment,
                potency_min=pet_totals[deployment][0],
                potency_max=pet_totals[deployment][1],
                missing_finishers=tuple(
                    finisher
                    for finisher in ("Pile Bunker", "Crowned Collider")
                    if finisher not in pet_landed_actions[deployment]
                )
                if deployment.actor == "Automaton Queen"
                else (),
            )
            for deployment in pet_deployments
        ),
        hit_outcomes=_summarize_hit_outcomes(landed),
        potion=PotionSummary(
            uses=len(potion_windows),
            potted_potency_min=potted_min,
            potted_potency_max=potted_max,
            gained_potency_min=potion_gain_min,
            gained_potency_max=potion_gain_max,
            windows=potion_windows,
        ),
        unmatched=tuple(sorted(unmatched.items(), key=lambda item: (-item[1], item[0]))),
        ghosted=tuple(sorted(ghosted.items(), key=lambda item: (-item[1], item[0]))),
        ghosted_times=tuple((name, tuple(times)) for name, times in sorted(ghosted_times.items())),
        luck_score=luck_weighted_bonus / luck_weighted_maximum if luck_weighted_maximum else 0.0,
        adjusted_luck_score=(
            max(
                0.0,
                min(
                    1.0,
                    (luck_weighted_bonus - luck_weighted_raid_adjustment) / luck_weighted_maximum,
                ),
            )
            if luck_weighted_maximum
            else 0.0
        ),
        luck_baseline=gear_baseline,
        critical_gear_baseline=combat_profile.critical_rate,
        direct_gear_baseline=combat_profile.direct_rate,
        direct_critical_gear_baseline=combat_profile.critical_rate * combat_profile.direct_rate,
    )
