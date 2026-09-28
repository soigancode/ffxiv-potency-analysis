"""Shared saved event and JSON helpers."""

import json
from pathlib import Path
from typing import Any

from .errors import AnalysisError


def _load_json(path: Path, expected: type) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"could not read {path}: {exc}") from exc
    if not isinstance(value, expected):
        raise AnalysisError(f"{path} must contain a JSON {expected.__name__}")
    return value


def _event_name(event: dict[str, Any], ability_names: dict[int, str]) -> str:
    game_id = event.get("abilityGameID")
    if not isinstance(game_id, int):
        return f"Unknown ability {game_id}"
    return ability_names.get(game_id, f"Unknown ability {game_id}")


def _has_buff(event: dict[str, Any], buff_id: int) -> bool:
    buffs = event.get("buffs")
    return isinstance(buffs, str) and str(buff_id) in buffs.split(".")


