"""Audit a Bard wipe with song speed changes and naturally expiring Weakness."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _print_analysis


def test_dancing_mad_wipe_shots_and_weakness_snapshots(
    extract_fight, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    extract_fight(
        "brd_dancing_mad_weakness_wipe.zip", "7y6BM2RwpTgvhW8C/fight-4/source-2/"
    )
    result = analyze_saved_fight(tmp_path, Path("data/jobs/brd/7.4/actions.json"))
    assert result.kill is False
    assert result.auto_attacks[0].hits == 198
    assert result.auto_attacks[0].weapon_delay_seconds == 3.04
    assert result.auto_attacks[0].estimated_delay_seconds == pytest.approx(3.08, abs=0.01)
    weakness_summary = next(row for row in result.damage_penalties if row.name == "Weakness")
    assert weakness_summary.lost_potency_min is not None
    assert weakness_summary.lost_potency_min > 0
    normal_factor = 100 + 237 * (6841 - 440) // 440
    weak_factor = 100 + 237 * (6841 * 75 // 100 - 440) // 440
    assert weakness_summary.multiplier == pytest.approx(weak_factor / normal_factor)
    assert weakness_summary.main_stat_reduction == 25
    assert weakness_summary.affected_hits == 162
    assert weakness_summary.first_observed_seconds == pytest.approx(544.515)
    assert weakness_summary.last_observed_seconds < 646

    events = json.loads((tmp_path / "damage-events.json").read_text())
    weakness = [event for event in events if event.get("type") == "damage"
                and "1000043" in event.get("buffs", "").split(".")]
    assert weakness
    # A DoT can retain a Weakness snapshot after it has expired on live hits.
    last_weak_tick = max(event["timestamp"] for event in weakness if event.get("tick"))
    last_weak_shot = max(event["timestamp"] for event in weakness
                         if event.get("abilityGameID") == 8)
    assert last_weak_tick > last_weak_shot
    assert [(window.name, window.start_seconds, window.end_seconds,
             window.end_reason) for window in result.status_windows] == [
        ("Dead", pytest.approx(534.661), pytest.approx(543.624),
         "revived: Weakness applied"),
        ("Weakness", pytest.approx(543.624), pytest.approx(643.633), "expired"),
        ("Dead", pytest.approx(654.223), pytest.approx(678.375), "fight ended"),
    ]
    assert (result.status_windows[1].end_seconds
            - result.status_windows[1].start_seconds) == pytest.approx(100.009)

    _print_analysis(result)
    output = capsys.readouterr().out
    assert "Fight: Dancing Mad (umad) | Duration: 11m18s (wipe)" in output
    assert "08m55s: died -> 09m04s: revived | Time dead: 9.0s | Weakness applied" in output
    assert "Weakness 09m04s 10m44s" in " ".join(output.split())
    assert "Potency lost" in output
    assert "Deaths: 2\n" in output
    assert "death(s)" not in output
    assert "10m54s: died -> 11m18s: fight ended" in output


def test_dancing_mad_wipe_all_ghosted_casts_and_reasons(
    extract_fight, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    extract_fight(
        "brd_dancing_mad_weakness_wipe.zip", "7y6BM2RwpTgvhW8C/fight-4/source-2/"
    )
    result = analyze_saved_fight(tmp_path, Path("data/jobs/brd/7.4/actions.json"))
    _print_analysis(result)
    output = capsys.readouterr().out
    ghosted = output.split("Ghosted attacks and reduced hits:\n", 1)[1].split("\n\n", 1)[0]
    observed_lines = ["  " + line.strip() for line in ghosted.splitlines() if line.strip()[:2].isdigit()]
    expected_lines = [
        "  03m18s Burst Shot on Kefka (target became untargetable before hit landed)",
        "  06m19s Burst Shot on Kefka (phase HP lock)",
        "  06m20s Heartbreak Shot on Kefka (phase HP lock)",
        "  06m22s Refulgent Arrow on Kefka (phase HP lock)",
        "  06m22s Empyreal Arrow on Kefka (phase HP lock)",
        "  08m52s Burst Shot on Chaos (player defeated before hit landed)",
        "  09m06s Caustic Bite on Chaos (target stopped taking damage before hit landed)",
        "  10m52s Burst Shot on Exdeath (player defeated before hit landed)",
    ]
    assert sorted(observed_lines) == sorted(expected_lines)
