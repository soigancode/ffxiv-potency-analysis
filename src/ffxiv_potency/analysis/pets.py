"""Reconstruct gauge spend and attribute pet hits to deployments."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .errors import AnalysisError
from .events import _event_name
from .models import PetDeploymentSummary
from .profiles import _PetProfile


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


