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
    actions = Path(__file__).resolve().parents[2] / "data/jobs/brd/7.4/actions.json"
    _print_analysis(analyze_saved_fight(tmp_path, actions))
    output = capsys.readouterr().out.split("Ghosted attacks and reduced hits:\n", 1)[1].split("\nHit Bonus and Luck:", 1)[0]

    assert "03m 18s Burst Shot Kefka target became untargetable before hit landed" in " ".join(output.split())
    for timestamp, action, target in (
        ("06m 12s", "Resonant Arrow", "Kefka"),
        ("06m 21s", "Empyreal Arrow", "Kefka"),
        ("11m 48s", "Burst Shot", "Exdeath"),
        ("11m 50s", "Burst Shot", "Exdeath"),
        ("11m 58s", "Burst Shot", "Exdeath"),
    ):
        assert f"{timestamp} {action} {target} phase HP lock" in " ".join(output.split())
    assert "target defeated" not in output


@pytest.mark.parametrize(
    "archive_name,prefix,expected",
    [
        (
            "brd_dancing_mad.zip",
            "7CANHrvwKT6tp2Gx/fight-7/source-2/",
            ("06m 16s Burst Shot on Kefka", "11m 51s Burst Shot on Exdeath",
             "12m 00s Iron Jaws on Chaos"),
        ),
        (
            "brd_dancing_mad_rank2.zip",
            "ApcPadnzZx1brm4T/fight-4/source-10/",
            ("06m 17s Burst Shot on Kefka", "11m 52s Burst Shot on Exdeath",
             "12m 00s Burst Shot on Exdeath"),
        ),
    ],
)
def test_top_two_bards_have_phase_hp_locks_not_defeated_targets(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str],
    archive_name: str, prefix: str, expected: tuple[str, ...],
) -> None:
    extract_fight(archive_name, prefix)
    actions = Path(__file__).resolve().parents[2] / "data/jobs/brd/7.4/actions.json"
    _print_analysis(analyze_saved_fight(tmp_path, actions))
    output = capsys.readouterr().out.split("Ghosted attacks and reduced hits:\n", 1)[1].split("\nHit Bonus and Luck:", 1)[0]
    for line in expected:
        assert line.replace(" on ", " ") + " phase HP lock" in " ".join(output.split())
    assert "target defeated" not in output
