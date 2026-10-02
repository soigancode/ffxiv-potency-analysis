"""Luck outcomes, guaranteed hits and raid Crit/DH effects."""

from __future__ import annotations

from math import floor
from pathlib import Path
from typing import Any

from ..patches import LATEST_KNOWN_PATCH
from ..raid_effects import REQUIRED_EFFECTS, resolve_effects, select_effect_document
from .config import action_data_root
from .errors import AnalysisError
from .events import _event_name, _has_buff, _load_json
from .models import HitOutcomeSummary
from .profiles import _CombatProfile


def _summarize_hit_outcomes(events: list[dict[str, Any]]) -> HitOutcomeSummary:
    normal = critical = direct = critical_direct = unknown = 0
    for event in events:
        if event.get("tick"):
            # FF Logs does not expose a Crit/DH outcome for these periodic ticks.
            continue
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


def _load_raid_effects(actions_path: Path, *, played_patch: str | None = None) -> list[dict[str, Any]]:
    """Resolve effects for the fight patch, including parsed job action references."""
    patch = played_patch or _load_json(actions_path, dict).get("patch") or LATEST_KNOWN_PATCH
    data_root = action_data_root(actions_path)
    try:
        document = select_effect_document(data_root, patch)
        # Preserve older custom snapshots until their first manifest-based update.
        if not (data_root / "raid_effects/datasets.json").is_file():
            generated = data_root / "raid_effects" / f"{patch}.json"
            legacy = data_root / "raid_buffs" / str(patch) / "effects.json"
            path = generated if generated.is_file() else legacy
            if path.is_file():
                override = _load_json(path, dict)
                if override.get("patch") != patch:
                    raise ValueError("raid-effect snapshot patch does not match the requested patch")
                rows = override.get("effects")
                present = {(row.get("action"), row.get("rate")) for row in rows
                           if isinstance(row, dict)} if isinstance(rows, list) else set()
                if not (path == legacy and present == REQUIRED_EFFECTS - {
                    ("Devilment", "critical"), ("Devilment", "direct"),
                }):
                    document = override
        return resolve_effects(document, data_root, patch)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AnalysisError(f"raid-effect data for patch {patch!r} is missing or invalid: {exc}") from exc


def _raid_luck_adjustment(
    event: dict[str, Any],
    effects: list[dict[str, Any]],
    ability_names: dict[int, str],
    profile: _CombatProfile,
    *,
    critical_rate: float | None = None,
    critical_multiplier: float | None = None,
    guaranteed: bool = False,
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
    rate = profile.critical_rate if critical_rate is None else critical_rate
    strength = (
        profile.critical_damage_multiplier if critical_multiplier is None else critical_multiplier
    ) - 1
    if guaranteed:
        critical_bonus_multiplier = floor((1 + crit_bonus * strength) * 1000 + 1e-9) / 1000
        direct_bonus_multiplier = floor((1 + direct_bonus * 0.25) * 1000 + 1e-9) / 1000
        return (1 + strength) * 1.25 * (critical_bonus_multiplier * direct_bonus_multiplier - 1)
    before = (1 + rate * strength) * (1 + profile.direct_rate * 0.25)
    after = (1 + min(1.0, rate + crit_bonus) * strength) * (
        1 + min(1.0, profile.direct_rate + direct_bonus) * 0.25
    )
    return after - before
