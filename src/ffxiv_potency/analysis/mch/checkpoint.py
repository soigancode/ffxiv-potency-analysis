"""Reconstruct Lindwurm checkpoint Battery or mark the opening value unknown."""

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..errors import AnalysisError
from ..events import _load_json
from ..pets import _reconstruct_pet_deployments
from ..profiles import _PetProfile
from .battery import mch_battery_events


def mch_checkpoint_gauges(
    directory: Path, fight: dict[str, Any], source_id: int | None,
    actions: dict[str, dict[str, Any]], names: dict[int, str],
    profiles: dict[str, _PetProfile],
) -> tuple[dict[str, int], bool]:
    path = directory / "checkpoint-context.json"
    if not path.is_file():
        return {}, True
    context = _load_json(path, dict)
    if context.get("carry") is False:
        return {}, False
    if context.get("carry") == "unknown":
        return {}, True
    previous = context.get("previousFight")
    if (context.get("carry") is not True or not isinstance(previous, dict)
            or context.get("fightID") != fight.get("id")
            or context.get("sourceID") != source_id
            or previous.get("encounterID") != 104 or previous.get("kill") is not True
            or not isinstance(previous.get("startTime"), (int, float))
            or not isinstance(previous.get("endTime"), (int, float))
            or previous["endTime"] > fight.get("startTime", 0)):
        raise AnalysisError("invalid Lindwurm II checkpoint context")
    casts = context.get("casts")
    damage = context.get("damage")
    if not isinstance(casts, list) or not isinstance(damage, list):
        raise AnalysisError("Lindwurm II checkpoint casts or damage are missing")
    landed: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for event in damage:
        if (isinstance(event, dict) and event.get("type") == "damage"
                and event.get("hitType") != 10 and event.get("amount", 0) > 0
                and event.get("packetID") is not None):
            landed[(event["packetID"], event.get("abilityGameID"))].append(event)
    try:
        _, gauges = _reconstruct_pet_deployments(
            sorted((cast for cast in casts if isinstance(cast, dict)
                    and cast.get("sourceID") == source_id),
                   key=lambda event: event.get("timestamp", 0)),
            actions, names, landed, profiles, float(previous["startTime"]),
            gauge_events_by_packet={"Battery Gauge": mch_battery_events(damage, source_id)},
        )
    except AnalysisError as exc:
        if "Battery Gauge" not in str(exc):
            raise
        return {}, True
    # A Queen cast below the minimum reveals an unrecorded gain between pulls.
    # Let only that first deployment use the explicitly labelled assumption.
    minimum = profiles.get("Automaton Queen")
    return gauges, (minimum is not None and minimum.gauge_minimum is not None
                    and gauges.get("Battery Gauge", 0) < minimum.gauge_minimum)
