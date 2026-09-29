"""Patch checks for ranked kills and unranked reports."""

from datetime import UTC, datetime

import pytest

from ffxiv_potency.fflogs.partitions import current_partition, require_current_patch


@pytest.mark.parametrize("encounter,partition", [(101, 7), (105, 7), (1085, 1)])
def test_current_ranked_partition(encounter: int, partition: int) -> None:
    assert current_partition(encounter) == partition
    require_current_patch(
        {"id": 3, "encounterID": encounter},
        {"rankings": {"data": [{"fightID": 3, "partition": partition, "bracketData": 7.5}]}},
    )


def test_previous_partition_is_rejected_even_when_report_date_is_recent() -> None:
    fight = {"id": 3, "encounterID": 103, "startTime": 1000,
             "reportStartTime": datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1000}
    with pytest.raises(ValueError, match="partition 6; only the patch 7.5 partition \\(7\\)"):
        require_current_patch(
            fight, {"rankings": {"data": [{"fightID": 3, "partition": 6,
                                            "bracketData": 7.4}]}},
        )


def test_unranked_fight_uses_played_date_and_rejects_unknown_provenance() -> None:
    current = datetime(2026, 5, 1, tzinfo=UTC).timestamp() * 1000
    older = datetime(2026, 4, 27, tzinfo=UTC).timestamp() * 1000
    require_current_patch({"id": 4, "startTime": 500, "reportStartTime": current}, {})
    with pytest.raises(ValueError, match="predates patch 7.5"):
        require_current_patch({"id": 4, "startTime": 500, "reportStartTime": older}, {})
    with pytest.raises(ValueError, match="redownload it"):
        require_current_patch({"id": 4, "startTime": 500}, {})
