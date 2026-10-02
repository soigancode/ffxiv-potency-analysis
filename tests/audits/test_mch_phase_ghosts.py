"""Verify phase closures separately from real untargetability and final kills."""

from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.reporting import confirmed_ghosts


def test_cat_point_exdeath_lock_continues_after_last_dot_tick(tmp_path, extract_fight):
    extract_fight("mch_dancing_mad_battery_ghosts.zip", "FDmkjVwq1yBadHG4/fight-3/source-67/")
    actions = Path("data/jobs/mch/7.4/actions.json")
    result = analyze_saved_fight(tmp_path, actions)
    ghosts = confirmed_ghosts(result)
    assert [name for _, name, _, _ in ghosts] == ["Heated Clean Shot", "Drill"]
    assert [t for t, _, _, _ in ghosts] == pytest.approx([856.769, 1100.383])
    endings = {
        (name, time): reason for name, rows in result.ghosted_ending_times for time, reason in rows
    }
    for name, time in [
        ("Air Anchor", 713.077),
        ("Scattergun", 715.612),
        ("Scattergun", 718.107),
        ("Scattergun", 720.605),
    ]:
        assert endings[name, time] == "phase HP lock"
    assert analyze_saved_fight(tmp_path, actions) == result
