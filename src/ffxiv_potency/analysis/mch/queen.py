"""Annotate Queen deployments with finishers and manual overdrives."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from ..events import _event_name
from ..models import PetDeploymentSummary
from ..pets import _deployment_for_event


def summarize_mch_queen_deployments(
    deployments: tuple[PetDeploymentSummary, ...],
    casts: list[dict[str, Any]],
    names: dict[int, str],
    source_id: int | None,
    fight_start: float,
    totals: dict[PetDeploymentSummary, list[float]],
    landed_actions: dict[PetDeploymentSummary, Counter[str]],
) -> tuple[PetDeploymentSummary, ...]:
    overdrives: dict[PetDeploymentSummary, float] = {}
    for cast in casts:
        if _event_name(cast, names) != "Queen Overdrive" or cast.get("sourceID") != source_id:
            continue
        deployment = _deployment_for_event(
            "Automaton Queen", cast.get("timestamp"), deployments, fight_start
        )
        timestamp = cast.get("timestamp")
        if deployment is not None and isinstance(timestamp, (int, float)):
            seconds = (timestamp - fight_start) / 1000
            if deployment.timestamp_seconds <= seconds <= deployment.timestamp_seconds + 12:
                overdrives[deployment] = seconds
    return tuple(
        replace(
            deployment,
            potency_min=totals[deployment][0],
            potency_max=totals[deployment][1],
            mch_missing_finishers=tuple(
                finisher for finisher in ("Pile Bunker", "Crowned Collider")
                if finisher not in landed_actions[deployment]
            ) if deployment.actor == "Automaton Queen" else (),
            mch_overdrive_seconds=overdrives.get(deployment),
            landed_actions=tuple(sorted(landed_actions[deployment].items())),
        )
        for deployment in deployments
    )
