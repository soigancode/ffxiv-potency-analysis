"""Independent window attribution and potency-weighted alignment checks."""

import pytest

from ffxiv_potency.analysis.pld.alignment import summarize_alignment
from ffxiv_potency.analysis.pld.buffs import FIGHT_OR_FLIGHT


def test_nearest_windows_and_combined_targets_keep_totals():
    rows = [(900, 'Imperator', 580, False), (2000, 'Confiteor', 1000, True),
            (2000, 'Confiteor', 400, True), (21500, 'Blade of Honor', 1000, False),
            (59500, 'Expiacion', 450, False), (63000, 'Circle of Scorn', 140, True),
            (63000, 'Circle of Scorn', 30, True), (63000, 'Fast Blade', 220, True)]
    a = summarize_alignment(rows, {FIGHT_OR_FLIGHT: ((1000, 21000, 1.25),
                                                 (61000, 81000, 1.25))}, 0, 70000, 1.25)
    assert (a.inside_potency, a.outside_potency) == (1570, 2030)
    assert [(w.inside_potency, w.outside_potency) for w in a.windows] == [
        (1400, 1580), (170, 450),
    ]
    assert a.windows[1].end_seconds == 70
    assert sum(f.potential_gain for f in a.outside) == pytest.approx(2030 * .25)
    assert a.outside[-1].window_start_seconds == 61


def test_missing_buff_and_repeated_target_hits_remain_visible():
    a = summarize_alignment([(5000, 'Imperator', 580, False),
                             (5000, 'Imperator', 232, False)], {}, 1000, 10000, 1.25)
    assert a.windows == ()
    assert a.inside_potency == 0
    assert a.outside_potency == 812
    assert len(a.outside) == 1
    assert a.outside[0].seconds == 4
    assert a.outside[0].potential_gain == 203
    assert a.outside[0].window_start_seconds is None
