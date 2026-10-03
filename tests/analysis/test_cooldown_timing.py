"""Cooldown waits, continuous recharge, charge caps and unavailable evidence."""

import pytest

from ffxiv_potency.analysis.cooldown_timing import cooldown_timing, living_windows
from ffxiv_potency.analysis.pld.cooldowns import summarize_cooldowns
from ffxiv_potency.analysis.targetability import TargetableTime


def test_single_charge_waits_and_unused_tail():
    row = cooldown_timing('Test', (0, 65000, 135000), 60000, 1, 0, 200000,
                          ((0, 200000),))
    assert row.ready_seconds == 20
    assert row.longest_delay_seconds == 10
    assert not row.minimum


def test_recharge_continues_through_downtime_and_wait_spans_windows():
    row = cooldown_timing('Test', (0, 100000), 60000, 1, 0, 170000,
                          ((0, 62000), (80000, 170000)))
    assert row.ready_seconds == 32  # 2 + 20 before use, 10 at the end.
    assert row.longest_delay_seconds == 22


def test_opening_delay_is_not_invented_and_unused_action_is_unknown():
    row = cooldown_timing('Test', (30000,), 60000, 1, 0, 100000, ((0, 100000),))
    assert row.ready_seconds == row.longest_delay_seconds == 10
    unknown = cooldown_timing('Test', (), 60000, 1, 0, 100000, ((0, 100000),))
    assert unknown.ready_seconds is None and unknown.longest_delay_seconds is None


def test_charge_recharge_is_sequential_and_time_below_cap_is_excluded():
    row = cooldown_timing('Intervene', (0, 1000, 32000, 65000), 30000, 2,
                          0, 130000, ((0, 130000),))
    assert row.minimum
    assert row.ready_seconds == row.longest_delay_seconds == 9


def test_charge_cap_stops_recharge_until_the_next_use():
    row = cooldown_timing('Intervene', (0, 1000, 100000, 105000), 30000, 2,
                          0, 200000, ((0, 200000),))
    assert row.ready_seconds == 79  # Conservative cap 61-100, exact cap 160-200.
    assert row.longest_delay_seconds == 40


def test_phase_start_and_charge_cap_during_downtime():
    row = cooldown_timing('Intervene', (0,), 30000, 2, 10000, 100000,
                          ((10000, 20000), (90000, 100000)))
    assert row.ready_seconds == row.longest_delay_seconds == 10


def test_deaths_are_removed_without_pausing_recharge():
    life = [{'type': 'death', 'targetID': 1, 'timestamp': 50000},
            {'type': 'resurrect', 'targetID': 1, 'timestamp': 80000},
            {'type': 'death', 'targetID': 2, 'timestamp': 10000}]
    windows = living_windows(((0, 100000),), life, 1, 0, 100000)
    assert windows == ((0, 50000), (80000, 100000))
    row = cooldown_timing('Test', (0,), 60000, 1, 0, 100000, windows)
    assert row.ready_seconds == row.longest_delay_seconds == 20
    assert living_windows(((0, 100000),), life[:1], 1, 0, 100000) == ((0, 50000),)


@pytest.mark.parametrize('targetable,expected', [
    (TargetableTime(None, 'unavailable'), None),
    (TargetableTime(100, 'FF Logs DPS duration'), None),
    (TargetableTime(0, 'events', ()), 0),
    (TargetableTime(100, 'events', ((0, 100000),)), 40),
])
def test_pld_uses_reference_recast_and_does_not_invent_targetability(targetable, expected):
    rows = summarize_cooldowns(
        [{'timestamp': 0, 'abilityGameID': 1}],
        {'Fight or Flight': {'recast_seconds': 60}}, {1: 'Fight or Flight'},
        [], 1, 0, 100000, targetable,
    )
    assert rows[0].ready_seconds == expected
    assert rows[1].ready_seconds is None
