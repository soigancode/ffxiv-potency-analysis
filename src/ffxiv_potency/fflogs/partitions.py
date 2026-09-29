"""Restrict analysis to the FF Logs partitions audited for patch 7.5."""

from datetime import UTC, datetime
from typing import Any

# The Savage tier uses a new partition in 7.5; Dancing Mad began in 7.51.
CURRENT_PARTITIONS = {101: 7, 102: 7, 103: 7, 104: 7, 105: 7, 1085: 1}
_PATCH_START_MS = datetime(2026, 4, 28, 10, tzinfo=UTC).timestamp() * 1000


def current_partition(encounter_id: int) -> int:
    try:
        return CURRENT_PARTITIONS[encounter_id]
    except KeyError as exc:
        raise ValueError(f"no current partition configured for encounter {encounter_id}") from exc


def require_current_patch(fight: dict[str, Any], rankings: dict[str, Any]) -> None:
    """Prefer FF Logs' ranking partition; date-check unranked fights and wipes."""
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
    expected = CURRENT_PARTITIONS.get(encounter_id) if isinstance(encounter_id, int) else None
    if expected is not None and partitions and partitions != {expected}:
        found = ", ".join(str(value) for value in sorted(partitions))
        raise ValueError(
            f"fight belongs to FF Logs partition {found}; only the patch 7.5 "
            f"partition ({expected}) is supported for this encounter"
        )
    if brackets and brackets != {7.5}:
        found = ", ".join(str(value) for value in sorted(brackets))
        raise ValueError(f"fight was played in patch {found}; only patch 7.5 is supported")
    if (expected is not None and partitions == {expected}) or brackets == {7.5}:
        return

    report_start = fight.get("reportStartTime")
    relative_start = fight.get("startTime")
    if not isinstance(report_start, (int, float)) or not isinstance(relative_start, (int, float)):
        raise ValueError(  # noqa: TRY004 - missing provenance, not a caller type error
            "cannot identify this fight's FF Logs partition or patch; "
            "redownload it to save its report date"
        )
    if report_start + relative_start < _PATCH_START_MS:
        raise ValueError("fight predates patch 7.5; earlier job balance changes are not audited")
