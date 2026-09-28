"""Luck outcomes, guaranteed hits and raid Crit/DH effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..patches import LATEST_KNOWN_PATCH
from .config import reference_path
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


def _load_raid_effects(actions_path: Path) -> list[dict[str, Any]]:
    """Use the refreshed guide snapshot for the action patch when available."""
    patch = _load_json(actions_path, dict).get("patch") or LATEST_KNOWN_PATCH
    bundled = reference_path("raid_effects", f"{patch}.json")
    if not bundled.is_file():
        raise AnalysisError(f"raid-effect data for patch {patch!r} is missing")
    bundled_document = _load_json(bundled, dict)
    data_root = actions_path.parent.parent.parent
    generated = data_root / "raid_effects" / f"{patch}.json"
    legacy = data_root / "raid_buffs" / str(patch) / "effects.json"
    if generated.is_file():
        document = _load_json(generated, dict)
    elif legacy.is_file():
        document = _load_json(legacy, dict)
    else:
        document = bundled_document
    if patch is not None and document.get("patch") != patch:
        raise AnalysisError(
            f"raid-effect data for patch {patch!r} is missing; run 'ffxiv-potency jobguide buffs'"
        )
    effects = document.get("effects")
    required = {(row["action"], row["rate"]) for row in bundled_document["effects"]}
    if isinstance(effects, list) and legacy.is_file() and not generated.is_file():
        present = {(row.get("action"), row.get("rate")) for row in effects if isinstance(row, dict)}
        if present == required - {("Devilment", "critical"), ("Devilment", "direct")}:
            # Existing 7.55 snapshots predate Devilment support. Use the
            # complete bundled data until they are refreshed.
            effects = bundled_document["effects"]
    if (
        not isinstance(effects, list)
        or len(effects) != len(required)
        or any(not isinstance(row, dict) for row in effects)
        or {(row.get("action"), row.get("rate")) for row in effects} != required
    ):
        raise AnalysisError("raid-effect snapshot must contain all configured crit/DH effects")
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
