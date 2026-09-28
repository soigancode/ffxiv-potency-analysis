"""Bard DoT potency and Iron Jaws refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..damage import landed_fraction
from ..dots import DotRules, DotTick, reconstruct_dot_ticks
from .buffs import bard_self_buff_windows

DOT_NAMES = frozenset({"Caustic Bite", "Stormbite"})
DIRECT_NAMES = DOT_NAMES | {"Iron Jaws"}
DOT_DURATION_MS = 45_000


@dataclass(frozen=True, slots=True)
class BardDotActionSummary:
    name: str
    landed_uses: int
    ticks: int
    direct_potency: float
    tick_potency: float

    @property
    def total_potency(self) -> float:
        return self.direct_potency + self.tick_potency


def reconstruct_bard_dots(
    damage: list[dict[str, Any]],
    ability_names: dict[int, str],
    source_id: int,
) -> tuple[DotTick, ...]:
    """Apply Bard's Iron Jaws refresh rules to the shared tick matcher."""
    return reconstruct_dot_ticks(
        damage, ability_names, source_id,
        DotRules(DOT_NAMES, DOT_DURATION_MS, refresh_action="Iron Jaws"),
    )


def bard_dot_potency(
    tick: DotTick,
    potency_per_tick: int,
    *,
    potion_multiplier: float,
    self_buff_windows: dict[int, tuple[tuple[int, int, float], ...]],
) -> float:
    """Apply only self-sourced damage buffs snapshotted at application.

    Buff windows map status IDs to (start, end, multiplier). Callers must
    establish their source from buff events. Crit/DH and other players' damage
    buffs affect actual damage, not personal potency.
    """
    if not tick.matched or tick.snapshot_timestamp is None:
        raise ValueError("cannot calculate potency for an unmatched Bard DoT tick")
    if potency_per_tick <= 0 or potion_multiplier <= 0:
        raise ValueError("potency and potion multiplier must be positive")
    return tick.landed_fraction * _buffed_potency(
        potency_per_tick, tick.snapshot_timestamp, tick.snapshot_buffs,
        potion_multiplier, self_buff_windows,
    )


def _buffed_potency(
    base: int,
    timestamp: int,
    buffs: str,
    potion_multiplier: float,
    self_buff_windows: dict[int, tuple[tuple[int, int, float], ...]],
) -> float:
    status_ids = {int(value) for value in buffs.strip(".").split(".") if value.isdigit()}
    multiplier = potion_multiplier if 1000049 in status_ids else 1.0
    for status_id, windows in self_buff_windows.items():
        if status_id in status_ids:
            for start, end, buff_multiplier in windows:
                if start <= timestamp < end:
                    multiplier *= buff_multiplier
                    break
    return base * multiplier


def summarize_bard_dots(
    casts: list[dict[str, Any]],
    damage: list[dict[str, Any]],
    buffs: list[dict[str, Any]],
    ability_names: dict[int, str],
    actions: dict[str, dict[str, Any]],
    source_id: int,
    *,
    potion_multiplier: float,
) -> tuple[BardDotActionSummary, ...]:
    """Calculate initial hits, Iron Jaws hits and all DoT ticks.

    An unresolvable tick fails rather than understating the fight's potency.
    """
    windows = bard_self_buff_windows(casts, buffs, ability_names, source_id)
    potency: dict[str, list[float]] = {name: [0, 0, 0.0, 0.0] for name in DIRECT_NAMES}
    for event in damage:
        if (event.get("type") != "damage" or event.get("sourceID") != source_id
            or event.get("tick") or event.get("hitType") == 10
            or event.get("amount") == 0):
            continue
        ability_id = event.get("abilityGameID")
        name = ability_names.get(ability_id) if isinstance(ability_id, int) else None
        if name not in DIRECT_NAMES:
            continue
        base = actions[name]["potency"]["base"]
        if not isinstance(base, int):
            raise TypeError(f"no direct potency for {name}")
        row = potency[name]
        row[0] += 1
        row[2] += landed_fraction(event) * _buffed_potency(
            base, event["timestamp"], str(event.get("buffs", "")),
            potion_multiplier, windows,
        )
    for tick in reconstruct_bard_dots(damage, ability_names, source_id):
        per_tick = actions[tick.name]["potency"]["damage_over_time"]["potency_per_tick"]
        row = potency[tick.name]
        row[1] += 1
        row[3] += bard_dot_potency(
            tick, per_tick, potion_multiplier=potion_multiplier, self_buff_windows=windows
        )
    return tuple(
        BardDotActionSummary(name, int(row[0]), int(row[1]), row[2], row[3])
        for name, row in sorted(potency.items())
    )

