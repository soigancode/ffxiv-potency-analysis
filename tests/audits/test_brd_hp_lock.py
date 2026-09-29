"""Repeated overkill during Dancing Mad phases is an HP lock, not a defeat."""

from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _print_analysis


def test_dancing_mad_hp_locks_explain_ghosted_casts(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight(
        "brd_dancing_mad_hp_lock.zip", "a-D6ZtNJ4Cbnf1ak8y/fight-6/source-198/"
    )
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    _print_analysis(analyze_saved_fight(tmp_path, actions))
    output = capsys.readouterr().out.split("Ghosted damaging casts:\n", 1)[1].split("\n\n", 1)[0]

    assert "03m18s Burst Shot on Kefka (target became untargetable before hit landed)" in output
    for timestamp, action, target in (
        ("06m12s", "Resonant Arrow", "Kefka"),
        ("06m21s", "Empyreal Arrow", "Kefka"),
        ("11m48s", "Burst Shot", "Exdeath"),
        ("11m50s", "Burst Shot", "Exdeath"),
        ("11m58s", "Burst Shot", "Exdeath"),
    ):
        assert f"{timestamp} {action} on {target} (phase HP lock; damage excluded)" in output
    assert "target defeated" not in output


@pytest.mark.parametrize(
    "archive_name,prefix,expected",
    [
        (
            "brd_dancing_mad.zip",
            "7CANHrvwKT6tp2Gx/fight-7/source-2/",
            ("06m16s Burst Shot on Kefka", "11m51s Burst Shot on Exdeath",
             "12m00s Iron Jaws on Chaos"),
        ),
        (
            "brd_dancing_mad_rank2.zip",
            "ApcPadnzZx1brm4T/fight-4/source-10/",
            ("06m17s Burst Shot on Kefka", "11m52s Burst Shot on Exdeath",
             "12m00s Burst Shot on Exdeath"),
        ),
    ],
)
def test_top_two_bards_have_phase_hp_locks_not_defeated_targets(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str],
    archive_name: str, prefix: str, expected: tuple[str, ...],
) -> None:
    extract_fight(archive_name, prefix)
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    _print_analysis(analyze_saved_fight(tmp_path, actions))
    output = capsys.readouterr().out.split("Ghosted damaging casts:\n", 1)[1].split("\n\n", 1)[0]
    for line in expected:
        assert line + " (phase HP lock; damage excluded)" in output
    assert "target defeated" not in output
