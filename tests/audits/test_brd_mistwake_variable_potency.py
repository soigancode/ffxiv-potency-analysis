"""Multi-target Apex gauge regression from Mistwake, report L7hjT31wtfBJkqPM."""

from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import analyze_saved_fight


def test_brd_mistwake_apex_certainty_uses_the_whole_cast(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str],
) -> None:
    extract_fight(
        "brd_mistwake_variable_potency.zip", "L7hjT31wtfBJkqPM/fight-4/source-2/",
    )
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    result = analyze_saved_fight(tmp_path, actions)
    apex = next(row for row in result.brd_potency_estimates if row.action == "Apex Arrow")

    assert result.fight_name == "Mistwake"
    assert result.unmatched == ()
    assert len(apex.apex_uses) == 13
    assert apex.estimated_hits == 35
    assert apex.uncertain_hits == sum(
        use.hits for use in apex.apex_uses if len(use.plausible_gauges) != 1
    ) == 18
    assert apex.weak_reference_hits == 19
    first_cast = next(use for use in apex.apex_uses if use.packet and use.packet[0] == 17080)
    assert (first_cast.hits, first_cast.plausible_gauges) == (7, (100,))

    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert "9 uses with ambiguous potency (18 affected hits)" in output
    assert "19 hits had fewer than 3 same-target reference hits" in output
