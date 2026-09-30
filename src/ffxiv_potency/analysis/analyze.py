"""Turn saved FF Logs events into an auditable potency report."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..fflogs.partitions import EXTREME_ENCOUNTERS
from ..jobguide.schema import ACTION_SCHEMA_VERSION
from ..patches import LATEST_KNOWN_PATCH
from .auto_attacks import _is_auto_attack, _summarize_auto_attacks
from .brd.barrage import _barrage_shadowbite_packets
from .brd.buffs import _brd_self_multiplier, brd_self_buff_windows
from .brd.dots import reconstruct_brd_dots, summarize_brd_dots
from .brd.songs import _brd_coda, _brd_song_durations
from .brd.variable_potency import _brd_damage_estimates
from .consumables import food_active, food_gaps, identify_consumable, initial_food_aura
from .damage import landed_fraction
from .echo import echo_status, is_echo_partition, normalize_echo_damage
from .errors import AnalysisError
from .events import _event_name, _has_buff, _load_json
from .luck import (
    _guaranteed_outcome_packets,
    _has_inherently_guaranteed_outcome,
    _load_raid_effects,
    _luck_contribution,
    _raid_luck_adjustment,
    _summarize_hit_outcomes,
)
from .mch.checkpoint import mch_checkpoint_gauges
from .mch.queen import summarize_mch_queen_deployments
from .mch.wildfire import MchWildfireTracker
from .models import (
    ActionSummary,
    AnalysisResult,
    PetDeploymentSummary,
    PotionSummary,
    ReducedDamageHit,
)
from .party import party_bonus_percent
from .penalties import (
    load_damage_penalties,
    penalty_multiplier,
    revival_multiplier,
    summarize_damage_penalties,
    summarize_revival_penalties,
    summarize_status_windows,
)
from .pets import _deployment_for_event, _reconstruct_pet_deployments
from .potency import _direct_potency, _is_channeled_action
from .potion import _potion_windows
from .profiles import _load_combat_profile, _load_pet_profiles


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
    debuffs_path = directory / "debuff-events.json"
    debuffs = _load_json(debuffs_path, list) if debuffs_path.is_file() else []
    life_path = directory / "life-events.json"
    life = _load_json(life_path, list) if life_path.is_file() else []
    revival_buffs_path = directory / "revival-buff-events.json"
    revival_buffs = _load_json(revival_buffs_path, list) if revival_buffs_path.is_file() else []
    targetability_path = directory / "targetability-events.json"
    targetability_events = (
        _load_json(targetability_path, list) if targetability_path.is_file() else []
    )
    overkill_path = directory / "encounter-overkill-events.json"
    encounter_overkills = _load_json(overkill_path, list) if overkill_path.is_file() else []
    combatants_path = directory / "combatant-info-events.json"
    combatants = _load_json(combatants_path, list) if combatants_path.is_file() else None
    rankings_path = directory / "rankings.json"
    rankings = _load_json(rankings_path, dict) if rankings_path.is_file() else {}
    action_document = _load_json(actions_path, dict)
    schema_version = action_document.get("schema_version")
    if schema_version is not None and schema_version != ACTION_SCHEMA_VERSION:
        raise AnalysisError(
            f"unsupported actions schema version {schema_version!r}; update the job-guide data"
        )
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
    encounter_id = fight.get("encounterID")
    penalty_rules = load_damage_penalties(encounter_id if isinstance(encounter_id, int) else None)
    raid_effects = _load_raid_effects(actions_path)

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
    initial_echo = echo_status(
        encounter_id if isinstance(encounter_id, int) else None, source_id, combatants,
    )
    if encounter_id in EXTREME_ENCOUNTERS:
        if initial_echo == "unknown":
            raise AnalysisError(
                "cannot verify whether this Extreme fight had Echo; "
                "the selected player's initial auras are missing"
            )
        if initial_echo == "observed":
            raise AnalysisError("Echo is not supported for Extreme trials")
    if is_echo_partition(fight.get("id"), rankings) and initial_echo != "observed":
        raise AnalysisError(
            "Echo partition requires the selected player's initial Echo aura; "
            "refresh the fight context before analysis"
        )
    if initial_echo == "observed":
        # Echo is absent from FF Logs' hit multiplier. Normalize the copied
        # outgoing events before DoT, overkill, and variable-potency analysis.
        raw_damage = normalize_echo_damage(raw_damage)

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
    if encounter_id in EXTREME_ENCOUNTERS:
        # The common status ID can appear on hits even when the report's
        # ability list does not include a named Damage Down entry.
        unknown_damage_down = (
            {1002911}
            | {ability_id for ability_id, name in ability_names.items() if name == "Damage Down"}
        ) - penalty_rules.keys()
        if any(_has_buff(event, status_id) for event in landed
               for status_id in unknown_damage_down):
            raise AnalysisError(
                "Damage Down potency is not configured for this Extreme fight; "
                "a fight log with its damage strength is needed before analysis"
            )
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
    encore_totals: dict[tuple[Any, Any], list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    pet_totals: dict[PetDeploymentSummary, list[float]] = defaultdict(lambda: [0.0, 0.0])
    pet_landed_actions: dict[PetDeploymentSummary, set[str]] = defaultdict(set)
    use_keys: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
    unmatched: dict[str, int] = defaultdict(int)
    auto_attack_events: list[dict[str, Any]] = []
    matched_events = 0
    potted_min = potted_max = potion_gain_min = potion_gain_max = 0.0
    damage_down_losses: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    revival_losses: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    luck_weighted_bonus = luck_weighted_maximum = luck_weighted_raid_adjustment = 0.0
    luck_weighted_expected = critical_rate_sum = direct_rate_sum = cdh_rate_sum = 0.0
    eligible_hit_count = 0
    missing_food: tuple[tuple[float, float], ...] = ()

    def record_damage_down_loss(
        event: dict[str, Any], penalized_min: float, penalized_max: float,
    ) -> None:
        """Compare each landed hit to itself with Damage Down removed."""
        for status_id, (_, multiplier) in penalty_rules.items():
            if multiplier < 1 and _has_buff(event, status_id):
                fraction_lost = 1 / multiplier - 1
                damage_down_losses[status_id][0] += penalized_min * fraction_lost
                damage_down_losses[status_id][1] += penalized_max * fraction_lost

    def record_revival_loss(
        event: dict[str, Any], penalized_min: float, penalized_max: float,
        *, potted: bool | None = None,
    ) -> None:
        """Remove only the active main-stat penalty from each landed player hit."""
        status_id = next(
            (status for status in (1000044, 1000043) if _has_buff(event, status)), None,
        )
        if status_id is None:
            return
        multiplier = revival_multiplier(event, combat_profile, potted=potted)
        if multiplier < 1:
            fraction_lost = 1 / multiplier - 1
            revival_losses[status_id][0] += penalized_min * fraction_lost
            revival_losses[status_id][1] += penalized_max * fraction_lost

    def record_luck(event: dict[str, Any], potency_weight: float) -> None:
        """Accumulate the same weighted outcome for actions, pets, and auto-attacks."""
        nonlocal luck_weighted_bonus, luck_weighted_maximum, luck_weighted_raid_adjustment
        nonlocal luck_weighted_expected, critical_rate_sum, direct_rate_sum, cdh_rate_sum
        nonlocal eligible_hit_count
        if event.get("tick"):
            return
        timestamp = event.get("timestamp")
        unfed = isinstance(timestamp, (int, float)) and not food_active(timestamp, missing_food)
        critical_multiplier = (
            combat_profile.unfed_critical_damage_multiplier if unfed
            else combat_profile.critical_damage_multiplier
        )
        critical_rate = (
            combat_profile.unfed_critical_rate if unfed else combat_profile.critical_rate
        )
        contribution = _luck_contribution(event, critical_multiplier)
        if contribution is None:
            return
        luck_weighted_bonus += potency_weight * contribution
        luck_weighted_raid_adjustment += potency_weight * _raid_luck_adjustment(
            event, raid_effects, ability_names, combat_profile,
            critical_rate=critical_rate, critical_multiplier=critical_multiplier,
        )
        maximum = critical_multiplier * 1.25 - 1
        luck_weighted_maximum += potency_weight * maximum
        luck_weighted_expected += potency_weight * (
            (1 + critical_rate * (critical_multiplier - 1))
            * (1 + combat_profile.direct_rate * 0.25) - 1
        )
        critical_rate_sum += critical_rate
        direct_rate_sum += combat_profile.direct_rate
        cdh_rate_sum += critical_rate * combat_profile.direct_rate
        eligible_hit_count += 1

    # Old audit fixtures retain the previous 5% assumption, labelled in the report.
    party_bonus = party_bonus_percent(fight, master_data, source_id)
    combat_profile = _load_combat_profile(
        job, action_document, party_bonus_percent=party_bonus if party_bonus is not None else 5,
    )
    missing_food = food_gaps(
        buffs, source_id, combat_profile.food_buff_id, float(start), float(end),
        initially_fed=initial_food_aura(combatants, source_id, combat_profile.food_buff_id),
    )
    food = identify_consumable(
        buffs, sorted_casts, ability_names, source_id,
        combat_profile.food_buff_id, combat_profile.food_name,
    )
    if missing_food == ((float(start), float(end)),):
        food = None
    potion_item = identify_consumable(
        buffs, sorted_casts, ability_names, source_id,
        combat_profile.potion_buff_id, combat_profile.potion_action_names[0],
        cast_names=combat_profile.potion_action_names,
    )
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
        # BRD DoTs and MCH Wildfire retain the potion present when applied.
        # Their later damage must not be mistaken for another potion use.
        snapshot_extension_ms=(
            45000 if job.casefold() == "bard"
            else 12000 if job.casefold() == "machinist"
            else 0
        ),
    )
    brd_self_windows = (
        brd_self_buff_windows(sorted_casts, buffs, ability_names, source_id)
        if job.casefold() == "bard" and source_id is not None else {}
    )
    brd_ticks = (
        {
            (tick.timestamp, tick.application_packet, tick.target_id): tick
            for tick in reconstruct_brd_dots(raw_damage, ability_names, source_id)
        }
        if job.casefold() == "bard" and source_id is not None else {}
    )
    wildfire = (
        MchWildfireTracker(
            sorted_casts, buffs, ability_names, actions, landed_by_packet,
            potion_windows, source_id, float(start), float(end),
            combat_profile.potion_buff_id, combat_profile.player_potion_multiplier,
        )
        if job.casefold() == "machinist" else None
    )

    starting_gauges, unknown_initial_gauge = (
        mch_checkpoint_gauges(
            directory, fight, source_id, actions, ability_names, pet_profiles,
        ) if job.casefold() == "machinist" and encounter_id == 105 else ({}, False)
    )
    pet_deployments, _ = _reconstruct_pet_deployments(
        sorted_casts, actions, ability_names, landed_by_packet, pet_profiles, float(start),
        initial_gauges=starting_gauges,
        allow_unknown_initial_gauge=unknown_initial_gauge,
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
            description = candidate_action.get("description", [])
            hits_multiple_targets = isinstance(description, list) and any(
                isinstance(line, str) and "all enemies" in line.casefold()
                for line in description
            )
            is_single_target_weaponskill = (
                isinstance(action_type, str)
                and "weaponskill" in action_type.lower()
                and isinstance(candidate_potency, dict)
                and candidate_potency.get("falloff") is None
                and not hits_multiple_targets
            )
            if not is_single_target_weaponskill:
                continue
            packet = (candidate.get("packetID"), candidate.get("abilityGameID"))
            if candidate.get("packetID") is not None:
                modifier_bonuses[packet] += bonus
            used += 1
            if used == maximum_uses:
                break

    brd_estimates, potency_estimates = (
        _brd_damage_estimates(
            landed, sorted_casts, raw_damage, ability_names,
            combat_profile.critical_damage_multiplier,
            fight_start=start,
            potion_multiplier=combat_profile.player_potion_multiplier,
            potion_buff_id=combat_profile.potion_buff_id,
            unfed_critical_multiplier=combat_profile.unfed_critical_damage_multiplier,
            unfed_determination_ratio=combat_profile.unfed_determination_ratio,
            food_missing=missing_food,
            combat_profile=combat_profile,
        )
        if job.casefold() == "bard"
        else ({}, ())
    )
    brd_barrage_shadowbites = (
        _barrage_shadowbite_packets(sorted_casts, buffs, ability_names, source_id)
        if job.casefold() == "bard" and source_id is not None else set()
    )

    apex_potency_by_packet: dict[tuple[int | None, int | None], float] = defaultdict(float)
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
        if name == "Wildfire" and wildfire is not None and event.get("tick") and isinstance(triggered, dict):
            maximum_triggers = triggered.get("maximum_triggers")
            potency_per_trigger = triggered.get("potency_per_trigger")
            if isinstance(maximum_triggers, int) and isinstance(potency_per_trigger, int):
                value = wildfire.record(event, maximum_triggers, potency_per_trigger)
                if value is not None:
                    values = value, value
        if values is None:
            key = (event.get("packetID"), event.get("abilityGameID"))
            estimate = brd_estimates.get(id(event))
            if estimate is not None:
                values = estimate[0], estimate[0]
            else:
                values = _direct_potency(
                action,
                event,
                is_primary_target=event.get("packetID") is None or event is primary_hits.get(key),
                modifier_bonus=modifier_bonuses.get(key, 0),
                source_multiplier=profile.potency_multiplier if profile is not None else 1.0,
                gauge_spent=deployment.gauge_spent if deployment is not None else None,
                gauge_minimum=profile.gauge_minimum if profile is not None else None,
                gauge_maximum=profile.gauge_maximum if profile is not None else None,
                base_potency_override=(
                    potency["conditional_potencies"].get("Barrage")
                    if key in brd_barrage_shadowbites
                    and isinstance(potency, dict)
                    and isinstance(potency.get("conditional_potencies"), dict)
                    else None
                ),
                )
        if values is None:
            unmatched[name] += 1
            continue

        fraction = landed_fraction(event)
        values = values[0] * fraction, values[1] * fraction

        tick_timestamp = event.get("timestamp")
        tick_packet = event.get("packetID")
        tick_target = event.get("targetID")
        brd_tick = (
            brd_ticks.get((tick_timestamp, tick_packet, tick_target))
            if job.casefold() == "bard" and event.get("tick")
            and isinstance(tick_timestamp, int)
            and isinstance(tick_packet, int)
            and isinstance(tick_target, int)
            else None
        )
        if job.casefold() == "bard":
            if event.get("tick") and name in {"Caustic Bite", "Stormbite"} and (
                brd_tick is None or not brd_tick.matched or brd_tick.snapshot_timestamp is None
            ):
                raise AnalysisError(f"cannot match {name} tick to a landed DoT application")
            buff_string = brd_tick.snapshot_buffs if brd_tick is not None else str(event.get("buffs", ""))
            snapshot_time = brd_tick.snapshot_timestamp if brd_tick is not None else None
            event_time = event.get("timestamp")
            buff_time = snapshot_time if snapshot_time is not None else (
                float(event_time) if isinstance(event_time, (int, float)) else 0.0
            )
            factor = _brd_self_multiplier(buff_string, buff_time, brd_self_windows)
            values = values[0] * factor, values[1] * factor

        if name == "Wildfire" and wildfire is not None and event.get("tick") and isinstance(triggered, dict):
            potted = id(event) in wildfire.potted_events
        else:
            potted = _has_buff(
                {"buffs": brd_tick.snapshot_buffs} if brd_tick is not None else event,
                combat_profile.potion_buff_id,
            )
        penalty = penalty_multiplier(event, penalty_rules)
        unpotted_values = tuple(value * penalty for value in values)
        if source_actor is None:
            penalty *= revival_multiplier(event, combat_profile, potted=potted)
            unpotted_values = tuple(
                value * revival_multiplier(event, combat_profile, potted=False)
                for value in unpotted_values
            )
        values = values[0] * penalty, values[1] * penalty

        if potted:
            potion_multiplier = (
                combat_profile.pet_potion_multipliers.get(
                    source_actor, combat_profile.player_potion_multiplier
                )
                if isinstance(source_actor, str)
                else combat_profile.player_potion_multiplier
            )
            potted_min += unpotted_values[0]
            potted_max += unpotted_values[1]
            potion_gain_min += values[0] * potion_multiplier - unpotted_values[0]
            potion_gain_max += values[1] * potion_multiplier - unpotted_values[1]
            values = values[0] * potion_multiplier, values[1] * potion_multiplier

        record_damage_down_loss(event, *values)
        if source_actor is None:
            record_revival_loss(event, *values, potted=potted)

        if name == "Wildfire" and wildfire is not None and event.get("tick"):
            wildfire.set_landed_potency(event, sum(values) / 2)

        if name == "Apex Arrow":
            apex_potency_by_packet[(event.get("packetID"), event.get("abilityGameID"))] += (
                values[0] + values[1]
            ) / 2

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
        if name == "Radiant Encore" and event.get("packetID") is not None:
            encore_row = encore_totals[(event["packetID"], event.get("abilityGameID"))]
            encore_row[0] += 1
            encore_row[1] += values[0]
            encore_row[2] += values[1]
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
    ghosted_targets: dict[str, list[tuple[float, str]]] = defaultdict(list)
    ghosted_target_low_hp: dict[str, list[tuple[float, int]]] = defaultdict(list)
    ghosted_ending_times: dict[str, list[tuple[float, str]]] = defaultdict(list)
    boss_events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in (*raw_damage, *casts, *encounter_overkills):
        if isinstance(event, dict) and isinstance(event.get("targetID"), int):
            boss_events[event["targetID"]].append(event)

    # Repeated overkill ticks while a boss remains present indicate a phase HP
    # lock. A single overkill instead fits an add dying at the end of a cast.
    overkill_by_target: dict[int, list[float]] = defaultdict(list)
    for event in encounter_overkills:
        target_id = event.get("targetID")
        event_time = event.get("timestamp")
        if (isinstance(target_id, int) and isinstance(event_time, (int, float))
                and isinstance(event.get("overkill"), (int, float))
                and event["overkill"] > 0):
            overkill_by_target[target_id].append(event_time)
    phase_lock_windows: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for target_id, times in overkill_by_target.items():
        if actors.get(target_id, {}).get("subType") != "Boss":
            # Adds such as Charnel Cells may keep receiving overkill from their
            # assigned player; this alone is not evidence of a boss HP lock.
            continue
        ordered = sorted(set(times))
        clusters: list[list[float]] = []
        for event_time in ordered:
            if not clusters or event_time - clusters[-1][-1] > 5000:
                clusters.append([])
            clusters[-1].append(event_time)
        for cluster in clusters:
            first, later = cluster[0], cluster[-1]
            # A shorter run of overkill can still be an HP lock when the
            # boss remains castable well after the first overkill. A defeat
            # may leave one lingering DoT tick, so require three distinct
            # overkill times and a later targeted player cast.
            short_lock_evidence = (
                later - first >= 1000 and len(cluster) >= 3
                and any(
                    cast.get("targetID") == target_id
                    and isinstance(cast.get("timestamp"), (int, float))
                    and first + 1500 <= cast["timestamp"] <= later + 2500
                    for cast in casts
                )
            )
            if later - first < 2000 and not short_lock_evidence:
                continue
            disappear = min(
                (
                    event["timestamp"] for event in targetability_events
                     if event.get("sourceID") == target_id
                     and event.get("targetable") == 0
                     and isinstance(event.get("timestamp"), (int, float))
                     and later <= event["timestamp"] <= later + 5000),
                default=later + 4000,
            )
            phase_lock_windows[target_id].append((first - 1000, disappear))

    # FF Logs can record the death event about two seconds after the lethal
    # damage. Match both records so an earlier, survived overkill does not
    # incorrectly label a cast as interrupted by death.
    lethal_player_hits = [
        hit
        for hit in encounter_overkills
        if hit.get("targetID") == source_id
        and isinstance(hit.get("timestamp"), (int, float))
        and any(
            death.get("type") == "death"
            and death.get("targetID") == source_id
            and death.get("killerID") == hit.get("sourceID")
            and death.get("killingAbilityGameID") == hit.get("abilityGameID")
            and isinstance(death.get("timestamp"), (int, float))
            and 0 <= death["timestamp"] - hit["timestamp"] <= 2500
            for death in life
        )
    ]

    def record_ghost(name: str, cast: dict[str, Any]) -> None:
        ghosted[name] += 1
        timestamp = cast.get("timestamp")
        if isinstance(timestamp, (int, float)):
            seconds = (timestamp - start) / 1000
            ghosted_times[name].append(seconds)
            target_id = cast.get("targetID")
            target = actors.get(target_id)
            if not isinstance(target, dict) or target.get("name") == "Environment":
                matching = next(
                    (
                        event for event in raw_damage
                        if isinstance(event, dict)
                        and event.get("packetID") is not None
                        and event.get("packetID") == cast.get("packetID")
                        and event.get("abilityGameID") == cast.get("abilityGameID")
                        and actors.get(event.get("targetID"), {}).get("name") != "Environment"
                    ),
                    None,
                )
                if matching is not None:
                    target_id = matching.get("targetID")
                    target = actors.get(target_id)
            if name in channel_casts and target_id == cast.get("sourceID"):
                # Channel initiation targets the player; only its later ticks
                # reveal a damage target. None landed for this ghosted cast.
                return
            if isinstance(target, dict) and isinstance(target.get("name"), str):
                ghosted_targets[name].append((seconds, target["name"]))
            target_resources = cast.get("targetResources")
            hit_points = target_resources.get("hitPoints") if isinstance(target_resources, dict) else None
            if not isinstance(target_id, int) or not isinstance(target, dict) or target.get("name") == "Environment":
                return
            if isinstance(hit_points, int) and not isinstance(hit_points, bool) and hit_points in (0, 1):
                ghosted_target_low_hp[name].append((seconds, hit_points))
                return
            following = [
                event
                for event in boss_events[target_id]
                if isinstance(event.get("timestamp"), (int, float))
                and timestamp < event["timestamp"] <= timestamp + 2500
            ]
            low_hp = next(
                (
                    event["targetResources"]["hitPoints"]
                    for event in sorted(following, key=lambda event: event["timestamp"])
                    if isinstance(event.get("targetResources"), dict)
                    and event["targetResources"].get("hitPoints") in (0, 1)
                ),
                None,
            )
            target_untargetable = any(
                isinstance(event, dict)
                and event.get("type") == "targetabilityupdate"
                and event.get("sourceID") == target_id
                and event.get("targetable") == 0
                and isinstance(event.get("timestamp"), (int, float))
                and timestamp <= event["timestamp"] <= timestamp + 2000
                for event in targetability_events
            )
            phase_locked = any(
                began <= timestamp <= finished
                for began, finished in phase_lock_windows[target_id]
            )
            if phase_locked:
                ghosted_ending_times[name].append((seconds, "phase HP lock; damage excluded"))
            elif target_untargetable:
                ghosted_ending_times[name].append(
                    (seconds, "target became untargetable before hit landed")
                )
            elif any(
                timestamp <= hit["timestamp"] <= timestamp + 2000
                for hit in lethal_player_hits
            ):
                ghosted_ending_times[name].append((seconds, "player defeated before hit landed"))
            elif low_hp is not None:
                ghosted_target_low_hp[name].append((seconds, low_hp))
            elif any(
                event.get("type") == "damage"
                and isinstance(event.get("overkill"), (int, float))
                and event["overkill"] > 0
                and event.get("packetID") != cast.get("packetID")
                and isinstance(event.get("timestamp"), (int, float))
                and timestamp - 500 <= event["timestamp"] <= timestamp + 2000
                for event in boss_events[target_id]
            ):
                ghosted_ending_times[name].append((seconds, "target defeated before hit landed"))
            elif any(
                event.get("type") == "damage" and event.get("tick")
                and event.get("amount") == 0
                for event in following
            ) and not any(
                event.get("type") == "damage"
                and isinstance(event.get("amount"), (int, float))
                and event["amount"] > 0
                for event in following
            ):
                ghosted_ending_times[name].append(
                    (seconds, "target stopped taking damage before hit landed")
                )
            elif end - timestamp <= 1500:
                ghosted_ending_times[name].append((seconds, "fight ending"))

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

    def landed_uses(name: str) -> int:
        if name in channel_casts:
            return len(channel_casts[name])
        potency = actions[name].get("potency")
        if isinstance(potency, dict) and isinstance(potency.get("damage_over_time"), dict):
            return len({
                (hit.get("packetID"), hit.get("abilityGameID"))
                for hit in landed
                if not hit.get("tick") and _event_name(hit, ability_names) == name
            })
        return len(use_keys[name])

    summaries = tuple(
        ActionSummary(
            name,
            int(values[0]),
            values[1],
            values[2],
            uses=landed_uses(name),
        )
        for name, values in sorted(totals.items(), key=lambda item: (-item[1][1], item[0]))
    )
    if auto_attack_events:
        auto_attacks, auto_potted, auto_gain = _summarize_auto_attacks(
            auto_attack_events, job, combat_profile, brd_self_windows, penalty_rules
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
            potency_weight = (
                auto_potency_by_name[str(event["_resolved_name"])] * landed_fraction(event)
            )
            if brd_self_windows:
                potency_weight *= _brd_self_multiplier(
                    str(event.get("buffs", "")), float(event.get("timestamp", 0)),
                    brd_self_windows,
                )
            if _has_buff(event, combat_profile.potion_buff_id):
                potency_weight *= combat_profile.player_potion_multiplier
            potency_weight *= penalty_multiplier(event, penalty_rules)
            potency_weight *= revival_multiplier(event, combat_profile)
            record_damage_down_loss(event, potency_weight, potency_weight)
            record_revival_loss(event, potency_weight, potency_weight)
            record_luck(event, potency_weight)
    gear_baseline = (
        luck_weighted_expected / luck_weighted_maximum if luck_weighted_maximum else 0.0
    )
    potency_estimates = tuple(
        replace(estimate, apex_uses=tuple(
            replace(use, potency=apex_potency_by_packet.get(use.packet, 0.0) if use.packet is not None else 0.0)
            for use in estimate.apex_uses
        )) if estimate.apex_uses else estimate
        for estimate in potency_estimates
    )
    _, brd_finales, brd_songs = (
        _brd_coda(sorted_casts, ability_names, float(start))
        if job.casefold() == "bard" else ({}, (), ())
    )
    brd_song_durations = (
        _brd_song_durations(sorted_casts, buffs, ability_names, source_id, float(end))
        if job.casefold() == "bard" else ()
    )
    if brd_finales:
        finale_encores: list[list[float]] = [[0, 0.0, 0.0] for _ in brd_finales]
        for cast in sorted_casts:
            if (_event_name(cast, ability_names) != "Radiant Encore"
                    or cast.get("sourceID") != source_id
                    or not isinstance(cast.get("timestamp"), (int, float))):
                continue
            encore_time = (cast["timestamp"] - start) / 1000
            finale_index = next(
                (
                    index for index in range(len(brd_finales) - 1, -1, -1)
                    if 0 <= encore_time - brd_finales[index].timestamp_seconds <= 30
                ),
                None,
            )
            if finale_index is None:
                continue
            row = encore_totals.get((cast.get("packetID"), cast.get("abilityGameID")))
            if row is not None:
                for i, value in enumerate(row):
                    finale_encores[finale_index][i] += value
        brd_finales = tuple(
            replace(
                finale,
                encore_hits=int(row[0]),
                encore_potency_min=row[1],
                encore_potency_max=row[2],
            )
            for finale, row in zip(brd_finales, finale_encores)
        )
    brd_dot_summary = (
        summarize_brd_dots(
            sorted_casts, raw_damage, buffs, ability_names, actions, source_id,
            potion_multiplier=combat_profile.player_potion_multiplier,
            damage_penalties=penalty_rules,
            combat_profile=combat_profile,
        )
        if job.casefold() == "bard" and source_id is not None else ()
    )
    return AnalysisResult(
        fight_name=str(fight.get("name", "Unknown fight")),
        kill=fight.get("kill") if isinstance(fight.get("kill"), bool) else None,
        encounter_id=fight.get("encounterID")
        if isinstance(fight.get("encounterID"), int)
        else None,
        source_name=str(source_name),
        party_bonus_percent=party_bonus,
        echo_status=initial_echo,
        ndps=ndps,
        rdps=rdps,
        dps=_find_ranking_amount(rankings.get("dps"), source_id, str(source_name)),
        duration_seconds=duration,
        raw_damage_events=len(raw_damage),
        landed_damage_events=len(landed),
        matched_damage_events=matched_events,
        potency_min=sum(item.potency_min for item in summaries) + auto_attack_potency,
        potency_max=sum(item.potency_max for item in summaries) + auto_attack_potency,
        actions=summaries,
        auto_attacks=auto_attacks,
        pet_deployments=summarize_mch_queen_deployments(
            pet_deployments, sorted_casts, ability_names, source_id, float(start),
            pet_totals, pet_landed_actions,
        ) if job.casefold() == "machinist" else tuple(
            replace(deployment, potency_min=pet_totals[deployment][0],
                    potency_max=pet_totals[deployment][1]) for deployment in pet_deployments
        ),
        mch_wildfires=wildfire.summaries() if wildfire is not None else (),
        brd_potency_estimates=potency_estimates,
        brd_songs=brd_songs,
        brd_song_durations=brd_song_durations,
        brd_finales=brd_finales,
        brd_dots=brd_dot_summary,
        hit_outcomes=_summarize_hit_outcomes(landed),
        potion=PotionSummary(
            uses=len(potion_windows),
            potted_potency_min=potted_min,
            potted_potency_max=potted_max,
            gained_potency_min=potion_gain_min,
            gained_potency_max=potion_gain_max,
            windows=potion_windows,
            item=potion_item,
        ),
        food=food,
        damage_penalties=(
            *summarize_damage_penalties(
                landed, penalty_rules, float(start), damage_down_losses,
            ),
            *summarize_revival_penalties(
                landed, ability_names, float(start), combat_profile, revival_losses,
            ),
        ),
        status_windows=summarize_status_windows(
            debuffs, life, ability_names, source_id, float(start), float(end), sorted_casts,
            revival_buffs,
        ),
        food_missing_windows=tuple(
            ((begin - start) / 1000, (finish - start) / 1000)
            for begin, finish in missing_food
        ),
        unmatched=tuple(sorted(unmatched.items(), key=lambda item: (-item[1], item[0]))),
        ghosted=tuple(sorted(ghosted.items(), key=lambda item: (-item[1], item[0]))),
        ghosted_times=tuple((name, tuple(times)) for name, times in sorted(ghosted_times.items())),
        ghosted_targets=tuple(
            (name, tuple(times)) for name, times in sorted(ghosted_targets.items())
        ),
        ghosted_target_low_hp=tuple(
            (name, tuple(times)) for name, times in sorted(ghosted_target_low_hp.items())
        ),
        ghosted_ending_times=tuple(
            (name, tuple(times)) for name, times in sorted(ghosted_ending_times.items())
        ),
        reduced_damage_hits=tuple(
            ReducedDamageHit(
                (event["timestamp"] - start) / 1000,
                _event_name(event, ability_names),
                event["amount"],
                event["overkill"],
                actors.get(event.get("targetID"), {}).get("name", ""),
            )
            for event in landed
            if isinstance(event.get("timestamp"), (int, float))
            and isinstance(event.get("amount"), (int, float))
            and event["amount"] > 0
            and isinstance(event.get("overkill"), (int, float))
            and event["overkill"] > 0
        ),
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
        critical_gear_baseline=(
            critical_rate_sum / eligible_hit_count if eligible_hit_count
            else combat_profile.critical_rate
        ),
        direct_gear_baseline=(
            direct_rate_sum / eligible_hit_count if eligible_hit_count
            else combat_profile.direct_rate
        ),
        direct_critical_gear_baseline=(
            cdh_rate_sum / eligible_hit_count if eligible_hit_count
            else combat_profile.critical_rate * combat_profile.direct_rate
        ),
    )
