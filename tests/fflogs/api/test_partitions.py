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


@pytest.mark.parametrize("partition,bracket", [
    (1, 7.4), (2, 7.4), (7, 7.5), (8, 7.5), (13, 7.5), (14, 7.5),
])
def test_global_savage_partitions_accept_their_patch_bracket(
    partition: int, bracket: float,
) -> None:
    assert current_partition(103, partition) == partition
    require_current_patch(
        {"id": 3, "encounterID": 103},
        {"rankings": {"data": [{"fightID": 3, "partition": partition,
                                "bracketData": bracket}]}},
    )


@pytest.mark.parametrize("partition", [1, 2])
def test_dancing_mad_standard_and_nonstandard_partitions(partition: int) -> None:
    assert current_partition(1085, partition) == partition
    require_current_patch(
        {"id": 3, "encounterID": 1085},
        {"rankings": {"data": [{"fightID": 3, "partition": partition,
                                "bracketData": 7.5}]}},
    )
    with pytest.raises(ValueError, match="only patch 7.5"):
        require_current_patch(
            {"id": 3, "encounterID": 1085},
            {"rankings": {"data": [{"fightID": 3, "partition": partition,
                                    "bracketData": 7.4}]}},
        )


def test_dancing_mad_rejects_other_partitions() -> None:
    with pytest.raises(ValueError, match="global partitions: 1, 2"):
        current_partition(1085, 3)
    with pytest.raises(ValueError, match="expected 1, 2"):
        require_current_patch(
            {"id": 3, "encounterID": 1085},
            {"rankings": {"data": [{"fightID": 3, "partition": 3,
                                    "bracketData": 7.5}]}},
        )


@pytest.mark.parametrize("encounter,partition,bracket", [
    (1083, 1, 7.4), (1083, 2, 7.4), (1083, 7, 7.5), (1083, 8, 7.5),
    (1084, 7, 7.5), (1084, 8, 7.5),
])
def test_extreme_partitions_and_patch_brackets(
    encounter: int, partition: int, bracket: float,
) -> None:
    assert current_partition(encounter, partition) == partition
    assert current_partition(encounter) == 7
    fight = {"id": 3, "encounterID": encounter}
    row = {"fightID": 3, "partition": partition, "bracketData": bracket}
    require_current_patch(fight, {"rankings": {"data": [row]}})
    with pytest.raises(ValueError, match="unexpected patch bracket"):
        require_current_patch(fight, {"rankings": {"data": [
            {**row, "bracketData": 7.5 if bracket == 7.4 else 7.4},
        ]}})


@pytest.mark.parametrize("encounter,allowed", [(1083, "1, 2, 7, 8"), (1084, "7, 8")])
def test_extreme_rejects_other_partitions(encounter: int, allowed: str) -> None:
    with pytest.raises(ValueError, match=f"global partitions: {allowed}"):
        current_partition(encounter, 9)
    with pytest.raises(ValueError, match=f"only global partitions {allowed}"):
        require_current_patch(
            {"id": 3, "encounterID": encounter},
            {"rankings": {"data": [{"fightID": 3, "partition": 9,
                                    "bracketData": 7.5}]}},
        )


@pytest.mark.parametrize("encounter,date,bracket", [
    (1083, datetime(2026, 2, 1, tzinfo=UTC), 7.4),
    (1083, datetime(2026, 5, 1, tzinfo=UTC), 7.5),
    (1084, datetime(2026, 5, 1, tzinfo=UTC), 7.5),
])
def test_unranked_extreme_uses_fight_date(
    encounter: int, date: datetime, bracket: float,
) -> None:
    fight = {"id": 3, "encounterID": encounter, "startTime": 1000,
             "reportStartTime": date.timestamp() * 1000}
    require_current_patch(fight, {})
    with pytest.raises(ValueError, match="patch bracket"):
        require_current_patch(fight, {"rankings": {"data": [
            {"fightID": 3, "bracketData": 7.5 if bracket == 7.4 else 7.4},
        ]}})


def test_unranked_extreme_requires_date_and_release() -> None:
    with pytest.raises(ValueError, match="report date"):
        require_current_patch({"encounterID": 1083}, {})
    with pytest.raises(ValueError, match="predates"):
        require_current_patch({"encounterID": 1084, "startTime": 0,
                               "reportStartTime": datetime(2026, 2, 1, tzinfo=UTC).timestamp() * 1000}, {})


def test_other_region_partition_is_rejected_even_when_report_date_is_recent() -> None:
    fight = {"id": 3, "encounterID": 103, "startTime": 1000,
             "reportStartTime": datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1000}
    with pytest.raises(ValueError, match="partition 9; only global partitions 1, 2, 7, 8, 13, 14"):
        require_current_patch(
            fight, {"rankings": {"data": [{"fightID": 3, "partition": 9,
                                            "bracketData": 7.5}]}},
        )
    with pytest.raises(ValueError, match="partition 9 is not supported"):
        current_partition(103, 9)


def test_mismatched_patch_bracket_is_rejected() -> None:
    with pytest.raises(ValueError, match="partition 1 has unexpected patch bracket"):
        require_current_patch(
            {"id": 3, "encounterID": 103},
            {"rankings": {"data": [{"fightID": 3, "partition": 1,
                                    "bracketData": 7.5}]}},
        )


def test_unranked_fight_uses_played_date_and_rejects_unknown_provenance() -> None:
    current = datetime(2026, 5, 1, tzinfo=UTC).timestamp() * 1000
    older = datetime(2026, 4, 27, tzinfo=UTC).timestamp() * 1000
    require_current_patch({"id": 4, "startTime": 500, "reportStartTime": current}, {})
    with pytest.raises(ValueError, match="predates patch 7.5"):
        require_current_patch({"id": 4, "startTime": 500, "reportStartTime": older}, {})
    with pytest.raises(ValueError, match="redownload it"):
        require_current_patch({"id": 4, "startTime": 500}, {})


@pytest.mark.parametrize("encounter,date,bracket", [
    (4549, datetime(2026, 2, 1, tzinfo=UTC), 7.4),
    (4549, datetime(2026, 5, 1, tzinfo=UTC), 7.5),
    (4550, datetime(2026, 3, 4, tzinfo=UTC), 7.4),
    (4551, datetime(2026, 5, 1, tzinfo=UTC), 7.5),
])
def test_dungeon_patch_uses_fight_date(encounter: int, date: datetime, bracket: float) -> None:
    assert current_partition(encounter) is None
    fight = {"id": 3, "encounterID": encounter, "startTime": 1000,
             "reportStartTime": date.timestamp() * 1000}
    require_current_patch(fight, {"rankings": {"data": [
        {"fightID": 3, "bracketData": bracket},
    ]}})
    with pytest.raises(ValueError, match="patch bracket"):
        require_current_patch(fight, {"rankings": {"data": [
            {"fightID": 3, "bracketData": 7.5 if bracket == 7.4 else 7.4},
        ]}})


def test_dungeon_rejects_pre_release_and_unverified_partition() -> None:
    with pytest.raises(ValueError, match="predates"):
        require_current_patch({"encounterID": 4550, "startTime": 0,
                               "reportStartTime": datetime(2026, 2, 1, tzinfo=UTC).timestamp() * 1000}, {})
    with pytest.raises(ValueError, match="verified selectable partition"):
        current_partition(4550, 1)
