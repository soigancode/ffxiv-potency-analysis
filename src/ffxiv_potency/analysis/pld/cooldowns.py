"""Paladin offensive cooldown timing from recorded casts."""

import re

from ..availability import action_lock_windows, cooldown_availability
from ..cooldown_timing import CooldownTiming, cooldown_timing, living_windows
from ..events import _event_name
from ..targetability import TargetableTime

OFFENSIVE_COOLDOWNS = (
    "Fight or Flight", "Imperator", "Circle of Scorn", "Expiacion", "Intervene",
)


def summarize_cooldowns(casts, actions, names, life, source: int, start: float, end: float,
                        targetable: TargetableTime, debuffs=(),
                        combatants=()) -> tuple[CooldownTiming, ...]:
    locks = action_lock_windows(debuffs, combatants, names, source, start, end)
    rows = []
    for name in OFFENSIVE_COOLDOWNS:
        action = actions.get(name, {})
        recast = action.get("recast_seconds")
        match = re.search(r"Maximum Charges: (\d+)", " ".join(action.get("description", ())))
        charges = int(match[1]) if match else 1
        times = tuple(float(e["timestamp"]) for e in casts if _event_name(e, names) == name)
        available = cooldown_availability(action, targetable, locks, start, end)
        if (available is None or not isinstance(recast, (int, float)) or recast <= 0):
            rows.append(CooldownTiming(name, None, None, charges > 1))
        else:
            windows = living_windows(available, life, source, start, end)
            rows.append(cooldown_timing(name, times, recast * 1000, charges,
                                       start, end, windows))
    return tuple(rows)
