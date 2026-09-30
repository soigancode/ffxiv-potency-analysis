"""Validate global ranking partitions and played dates of unranked fights."""

from datetime import UTC, datetime
from typing import Any

# Global Savage partitions verified against the M9S/MCH probe. The first
# of each pair uses standard compositions; the second is non-standard.
# China and Korea use different IDs and remain outside the configured data.
SAVAGE_PARTITIONS = {
    1: (7.4, False), 2: (7.4, False),
    7: (7.5, False), 8: (7.5, False),
    13: (7.5, True), 14: (7.5, True),
}
SAVAGE_ENCOUNTERS = frozenset({101, 102, 103, 104, 105})
EXTREME_PARTITIONS = {
    1083: {1: 7.4, 2: 7.4, 7: 7.5, 8: 7.5},  # Doomtrain.
    1084: {7: 7.5, 8: 7.5},                  # Enuo.
}
EXTREME_ENCOUNTERS = frozenset(EXTREME_PARTITIONS)
ULTIMATE_PARTITIONS = frozenset({1, 2})  # Dancing Mad: standard, non-standard.
CURRENT_PARTITIONS = {
    **dict.fromkeys(SAVAGE_ENCOUNTERS, 7),
    **dict.fromkeys(EXTREME_ENCOUNTERS, 7),
    1085: 1,
}
DUNGEON_RELEASES = {
    4550: datetime(2026, 3, 3, 10, tzinfo=UTC),    # Another Merchant's Tale, 7.45
    4549: datetime(2025, 12, 16, 10, tzinfo=UTC),  # Mistwake, 7.4
    4551: datetime(2026, 4, 28, 10, tzinfo=UTC),   # The Clyteum, 7.5
}
_PATCH_74_START_MS = datetime(2025, 12, 16, 10, tzinfo=UTC).timestamp() * 1000
_PATCH_75_START_MS = datetime(2026, 4, 28, 10, tzinfo=UTC).timestamp() * 1000


def current_partition(encounter_id: int, selected: int | None = None) -> int | None:
    """Choose a global partition, or use FF Logs' default for a dungeon."""
    if encounter_id in DUNGEON_RELEASES:
        if selected is not None:
            raise ValueError("dungeon rankings do not have a verified selectable partition")
        return None
    try:
        default = CURRENT_PARTITIONS[encounter_id]
    except KeyError as exc:
        raise ValueError(f"no current partition configured for encounter {encounter_id}") from exc
    if selected is None:
        return default
    if encounter_id in SAVAGE_ENCOUNTERS:
        allowed = SAVAGE_PARTITIONS
    elif encounter_id in EXTREME_ENCOUNTERS:
        allowed = EXTREME_PARTITIONS[encounter_id]
    elif encounter_id == 1085:
        allowed = ULTIMATE_PARTITIONS
    else:
        allowed = {default}
    if selected not in allowed:
        names = ", ".join(str(partition) for partition in sorted(allowed))
        raise ValueError(
            f"partition {selected} is not supported for encounter {encounter_id}; "
            f"global partitions: {names}"
        )
    return selected


def fight_partition_patch(fight: dict[str, Any], rankings: dict[str, Any]) -> tuple[str, str]:
    """Describe recorded ranking provenance; use played date where partitions are absent."""
    fight_id = fight.get("id")
    encounter_id = fight.get("encounterID")
    rows = []
    for metric in ("rankings", "rdps"):
        value = rankings.get(metric)
        data = value.get("data") if isinstance(value, dict) else None
        if isinstance(data, list):
            rows.extend(row for row in data if isinstance(row, dict)
                        and row.get("fightID") in (None, fight_id))
    partitions = {row["partition"] for row in rows
                  if isinstance(row.get("partition"), int) and not isinstance(row["partition"], bool)}
    brackets = {row["bracketData"] for row in rows
                if isinstance(row.get("bracketData"), (int, float))
                and not isinstance(row["bracketData"], bool)}
    partition = next(iter(partitions)) if len(partitions) == 1 else None
    patch = None
    if encounter_id in SAVAGE_ENCOUNTERS and partition in SAVAGE_PARTITIONS:
        patch = SAVAGE_PARTITIONS[partition][0]
    elif encounter_id in EXTREME_ENCOUNTERS and partition in EXTREME_PARTITIONS[encounter_id]:
        patch = EXTREME_PARTITIONS[encounter_id][partition]
    elif encounter_id not in DUNGEON_RELEASES and len(brackets) == 1:
        patch = next(iter(brackets))
    elif encounter_id == 1085:
        patch = 7.5
    else:
        start = fight.get("startTime")
        report_start = fight.get("reportStartTime")
        if isinstance(start, (int, float)) and isinstance(report_start, (int, float)):
            played_at = start + report_start
            if played_at >= _PATCH_75_START_MS:
                patch = 7.5
            elif played_at >= DUNGEON_RELEASES[4550].timestamp() * 1000:
                patch = 7.45
            elif played_at >= _PATCH_74_START_MS:
                patch = 7.4
    return (str(partition) if partition is not None else "n/a",
            str(patch) if patch is not None else "n/a")


def require_current_patch(fight: dict[str, Any], rankings: dict[str, Any]) -> None:
    """Check ranking provenance, retaining the 7.5 date fallback for old saves."""
    encounter_id = fight.get("encounterID")
    fight_id = fight.get("id")
    rows = []
    for metric in ("rankings", "rdps"):
        value = rankings.get(metric)
        data = value.get("data") if isinstance(value, dict) else None
        if isinstance(data, list):
            rows.extend(
                row for row in data
                if isinstance(row, dict) and row.get("fightID") in (None, fight_id)
            )
    partitions = {row["partition"] for row in rows if isinstance(row.get("partition"), int)}
    brackets = {row["bracketData"] for row in rows
                if isinstance(row.get("bracketData"), (int, float))}

    if encounter_id in DUNGEON_RELEASES:
        report_start = fight.get("reportStartTime")
        relative_start = fight.get("startTime")
        if not isinstance(report_start, (int, float)) or not isinstance(relative_start, (int, float)):
            raise ValueError("cannot identify this dungeon fight's played patch; redownload it to save its report date")
        played_at = report_start + relative_start
        if played_at < DUNGEON_RELEASES[encounter_id].timestamp() * 1000:
            raise ValueError("dungeon fight predates the encounter's release patch")
        played_patch = 7.4 if played_at < _PATCH_75_START_MS else 7.5
        allowed_brackets = {7.4, 7.45} if played_patch == 7.4 else {7.5}
        if brackets and not brackets.issubset(allowed_brackets):
            raise ValueError(
                f"dungeon fight date indicates patch {played_patch}, but FF Logs reports "
                f"patch bracket {sorted(brackets)}"
            )
        return

    if encounter_id in EXTREME_ENCOUNTERS:
        supported = EXTREME_PARTITIONS[encounter_id]
        if partitions:
            if len(partitions) != 1 or not partitions <= supported.keys():
                found = ", ".join(str(value) for value in sorted(partitions))
                allowed = ", ".join(str(value) for value in sorted(supported))
                raise ValueError(
                    f"fight belongs to FF Logs partition {found}; only global partitions "
                    f"{allowed} are supported for this encounter"
                )
            partition = next(iter(partitions))
            expected_bracket = supported[partition]
            if brackets and brackets != {expected_bracket}:
                raise ValueError(
                    f"partition {partition} has unexpected patch bracket {sorted(brackets)}; "
                    f"expected {expected_bracket}"
                )
            return
        report_start = fight.get("reportStartTime")
        relative_start = fight.get("startTime")
        if not isinstance(report_start, (int, float)) or not isinstance(relative_start, (int, float)):
            raise ValueError("cannot identify this unranked Extreme fight's played patch; redownload it to save its report date")
        played_at = report_start + relative_start
        release_ms = _PATCH_74_START_MS if encounter_id == 1083 else _PATCH_75_START_MS
        if played_at < release_ms:
            raise ValueError("Extreme fight predates the encounter's release patch")
        played_patch = 7.4 if played_at < _PATCH_75_START_MS else 7.5
        if brackets and brackets != {played_patch}:
            raise ValueError(
                f"Extreme fight date indicates patch {played_patch}, but FF Logs reports "
                f"patch bracket {sorted(brackets)}"
            )
        return

    if encounter_id in SAVAGE_ENCOUNTERS and partitions:
        if len(partitions) != 1 or next(iter(partitions)) not in SAVAGE_PARTITIONS:
            found = ", ".join(str(value) for value in sorted(partitions))
            allowed = ", ".join(str(value) for value in sorted(SAVAGE_PARTITIONS))
            raise ValueError(
                f"fight belongs to FF Logs partition {found}; only global partitions "
                f"{allowed} are supported for this encounter"
            )
        partition = next(iter(partitions))
        expected_bracket, _ = SAVAGE_PARTITIONS[partition]
        if brackets and brackets != {expected_bracket}:
            raise ValueError(
                f"partition {partition} has unexpected patch bracket {sorted(brackets)}; "
                f"expected {expected_bracket}"
            )
        return

    expected = CURRENT_PARTITIONS.get(encounter_id) if isinstance(encounter_id, int) else None
    if expected is not None:
        allowed = ULTIMATE_PARTITIONS if encounter_id == 1085 else frozenset({expected})
        if partitions and (len(partitions) != 1 or not partitions <= allowed):
            found = ", ".join(str(value) for value in sorted(partitions))
            names = ", ".join(str(value) for value in sorted(allowed))
            raise ValueError(f"fight belongs to FF Logs partition {found}; expected {names}")
    if brackets and brackets != {7.5}:
        found = ", ".join(str(value) for value in sorted(brackets))
        raise ValueError(f"fight was played in patch {found}; only patch 7.5 is supported")
    if (expected is not None and partitions) or brackets == {7.5}:
        return

    report_start = fight.get("reportStartTime")
    relative_start = fight.get("startTime")
    if not isinstance(report_start, (int, float)) or not isinstance(relative_start, (int, float)):
        raise ValueError(  # noqa: TRY004 - missing provenance is a user input error
            "cannot identify this fight's FF Logs partition or patch; "
            "redownload it to save its report date"
        )
    if report_start + relative_start < _PATCH_75_START_MS:
        raise ValueError(
            "unranked fight predates patch 7.5; an audited global partition is required "
            "for older Savage logs"
        )
