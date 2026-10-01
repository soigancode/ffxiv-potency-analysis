"""The second revival replaces Weakness with Brink; death ends each window."""

from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _print_analysis


def test_dancing_mad_brink_wipe(
    extract_fight, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    extract_fight("brd_dancing_mad_brink_wipe.zip", "wdV37v9K8mB4Xatq/fight-20/source-3/")
    result = analyze_saved_fight(tmp_path, Path("data/jobs/brd/7.4/actions.json"))
    assert result.kill is False
    assert result.encounter_id == 1085
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason)
            for w in result.status_windows] == [
        ("Dead", pytest.approx(659.088), pytest.approx(671.187),
         "revived: Weakness applied"),
        ("Weakness", pytest.approx(671.187), pytest.approx(676.036), "death"),
        ("Dead", pytest.approx(676.036), pytest.approx(688.85),
         "revived: Brink of Death applied"),
        ("Brink of Death", pytest.approx(688.85), pytest.approx(709.027), "death"),
        ("Dead", pytest.approx(709.027), pytest.approx(716.787), "fight ended"),
    ]
    observed = {penalty.name: penalty for penalty in result.damage_penalties}
    assert observed["Weakness"].affected_hits == 2
    assert observed["Brink of Death"].affected_hits == 32
    assert observed["Weakness"].lost_potency_min == pytest.approx(74.6571814)
    assert observed["Brink of Death"].lost_potency_min == pytest.approx(1797.1467526)
    normal = 100 + 237 * (6838 - 440) // 440
    brink = 100 + 237 * (6838 // 2 - 440) // 440
    assert observed["Brink of Death"].multiplier == pytest.approx(brink / normal)
    assert result.auto_attacks[0].weapon_delay_seconds == 3.04

    _print_analysis(result)
    output = capsys.readouterr().out
    assert "Weakness: 11m11s–11m16s (death)" in output
    assert "Brink of Death: 11m29s–11m49s (death)" in output
    assert "Weakness: 11m11s–11m16s (death)\n    main stat -25%; ~26.0% potency reduction; 2 landed hits affected; 75 potency lost" in output
    assert "Brink of Death: 11m29s–11m49s (death)\n    main stat -50%; ~51.9% potency reduction; 32 landed hits affected; 1,797 potency lost" in output
    assert (
        "10m57s Refulgent Arrow on Exdeath (player defeated before hit landed)"
        in output
    )
