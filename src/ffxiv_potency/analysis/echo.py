"""Read initial Echo auras and normalize supported Savage damage."""

from typing import Any

from ..fflogs.partitions import EXTREME_ENCOUNTERS, SAVAGE_PARTITIONS

ECHO_BUFF_ID = 1000042
HEAVYWEIGHT_SAVAGE = frozenset({101, 102, 103, 104, 105})
HEAVYWEIGHT_ECHO_DAMAGE_BONUS = 0.12
ECHO_PARTITIONS = frozenset({13, 14})


def echo_status(
    encounter_id: int | None,
    source_id: int | None,
    combatants: list[dict[str, Any]] | None,
) -> str | None:
    """Use the first combatant record, before any fight damage is processed."""
    if encounter_id not in HEAVYWEIGHT_SAVAGE and encounter_id not in EXTREME_ENCOUNTERS:
        return None
    if source_id is None or combatants is None:
        return "unknown"
    initial = next((event for event in combatants
                    if isinstance(event, dict) and event.get("sourceID") == source_id), None)
    auras = initial.get("auras") if initial is not None else None
    if not isinstance(auras, list):
        return "unknown"
    return ("observed" if any(isinstance(aura, dict) and aura.get("ability") == ECHO_BUFF_ID
                              for aura in auras) else "absent")


def is_echo_partition(fight_id: Any, rankings: dict[str, Any]) -> bool:
    """Recognize Echo rankings only as a safeguard when initial auras are missing."""
    for metric in ("rankings", "rdps"):
        value = rankings.get(metric)
        rows = value.get("data") if isinstance(value, dict) else None
        if isinstance(rows, list) and any(
            isinstance(row, dict) and row.get("fightID") in (None, fight_id)
            and row.get("partition") in ECHO_PARTITIONS for row in rows
        ):
            return True
    return False


def is_non_echo_partition(fight_id: Any, rankings: dict[str, Any]) -> bool:
    """Known pre-Echo Savage rankings establish zero Echo without initial auras."""
    partitions = set()
    for metric in ("rankings", "rdps"):
        value = rankings.get(metric)
        rows = value.get("data") if isinstance(value, dict) else None
        if isinstance(rows, list):
            partitions.update(
                row["partition"] for row in rows if isinstance(row, dict)
                and row.get("fightID") in (None, fight_id)
                and isinstance(row.get("partition"), int)
                and not isinstance(row["partition"], bool)
            )
    non_echo = {partition for partition, (_, echo) in SAVAGE_PARTITIONS.items() if not echo}
    return bool(partitions) and partitions.issubset(non_echo)


def normalize_echo_damage(events: list[Any]) -> list[Any]:
    """Copy outgoing damage at its pre-Echo value without changing saved FF Logs data."""
    factor = 1 + HEAVYWEIGHT_ECHO_DAMAGE_BONUS
    result = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in {"damage", "calculateddamage"}:
            result.append(event)
            continue
        normalized = event.copy()
        for field in ("amount", "unmitigatedAmount", "overkill"):
            value = event.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                normalized[field] = value / factor
        result.append(normalized)
    return result
