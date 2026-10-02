"""Audit Dancer damage and proc histories across complete Criterion runs."""

import pytest

CASES = [
    (
        "RNHKznJBqfPTmAG7/fight-4/source-4",
        ("Khana Ejinn", "savage_7_4", 389, 264, 3, 37, 76, 40, 40, 24),
        (48, 44, 40),
        55.19951993207276,
    ),
    (
        "dpKPfVbYAXrZGByM/fight-53/source-5",
        ("Zach Csv", "savage_7_4", 376, 256, 3, 37, 77, 41, 41, 17),
        (47, 41, 41),
        49.722986005561054,
    ),
    (
        "MVwpb426RqGQhFkt/fight-18/source-98",
        ("Jazar Spencer", "savage_7_4", 404, 263, 4, 37, 78, 44, 44, 27),
        (48, 48, 44),
        57.235712127666595,
    ),
]


@pytest.mark.parametrize("prefix,expected,trials,score", CASES)
def test_dancer_full_criterion_run(tmp_path, audit_dnc, prefix, expected, trials, score):
    result = audit_dnc(tmp_path, "dnc_another_merchants_tale.zip", prefix, expected, (0,))
    assert result.encounter_id == 4550
    assert result.party_bonus_percent == 4
    proc = result.dnc_procs
    assert proc is not None
    assert proc.starting_feathers_source == "fresh dungeon or Criterion run"
    assert tuple(sum(count for _, count in stage.trials) for stage in proc.ready_procs) == trials
    assert proc.fan_trials == trials[2]
    assert proc.combined_feather_luck_min == pytest.approx(score)
