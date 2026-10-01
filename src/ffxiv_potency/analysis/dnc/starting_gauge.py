"""Separate reset raid pulls from checkpoint and dungeon resource carry."""

from pathlib import Path
from typing import Any

from ...fflogs.partitions import DUNGEON_RELEASES, EXTREME_ENCOUNTERS, SAVAGE_ENCOUNTERS
from ..events import _load_json


def starting_feathers(
    directory: Path, fight: dict[str, Any], source_id: int | None
) -> tuple[tuple[int, ...], str]:
    encounter = fight.get("encounterID")
    if encounter == 105:
        path = directory / "checkpoint-context.json"
        context = _load_json(path, dict) if path.is_file() else {}
        if (
            context.get("fightID", fight.get("id")) != fight.get("id")
            or context.get("sourceID", source_id) != source_id
        ):
            return tuple(range(5)), "checkpoint carry-over unknown"
        if context.get("carry") is False:
            return (0,), "reset after checkpoint wipe"
        previous = context.get("previousFight")
        if (
            context.get("carry") is True
            and context.get("fightID") == fight.get("id")
            and context.get("sourceID") == source_id
            and isinstance(previous, dict)
            and previous.get("encounterID") == 104
            and previous.get("kill") is True
            and isinstance(previous.get("endTime"), (int, float))
            and isinstance(fight.get("startTime"), (int, float))
            and previous["endTime"] <= fight["startTime"]
        ):
            return tuple(range(5)), "phase-one carry-over"
        return tuple(range(5)), "checkpoint carry-over unknown"
    if encounter in DUNGEON_RELEASES:
        return (0,), "fresh dungeon or Criterion run"
    if encounter in SAVAGE_ENCOUNTERS or encounter in EXTREME_ENCOUNTERS or encounter == 1085:
        return (0,), "fresh raid or trial pull"
    return tuple(range(5)), "unsupported encounter starting gauge unknown"
