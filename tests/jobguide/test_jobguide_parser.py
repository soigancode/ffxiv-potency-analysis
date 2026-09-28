import re
from pathlib import Path

import pytest

from ffxiv_potency.jobguide import JobGuideParseError, parse_job_actions

FIXTURES = Path(__file__).parents[1] / "fixtures/jobguide"


def load_full_guide() -> str:
    return (FIXTURES / "machinist_full_7_5.html").read_text(encoding="utf-8")


def replace_action_text(action: str, original: str, replacement: str) -> str:
    """Mutate only one job-guide row, even when other actions share its wording."""
    html = load_full_guide()
    for match in re.finditer(r'<tr id="pve_action__\d+">.*?</tr>', html, re.DOTALL):
        row = match.group()
        if f"<strong>{action}</strong>" in row:
            assert original in row
            return (
                html[: match.start()] + row.replace(original, replacement, 1) + html[match.end() :]
            )
    raise AssertionError(f"missing {action} in full job-guide fixture")


def test_parses_drill() -> None:
    actions = parse_job_actions(load_full_guide())

    drill = next(action for action in actions if action.name == "Drill")
    assert drill.name == "Drill"
    assert drill.level == 58
    assert drill.action_type == "Weaponskill"
    assert drill.potency is not None
    assert drill.potency.base == 660
    assert drill.potency.combo is None
    assert "Maximum Charges: 2" in drill.description


def test_parses_combo_potency_and_non_damaging_action() -> None:
    actions = parse_job_actions(load_full_guide())

    heated_slug = next(action for action in actions if action.name == "Heated Slug Shot")
    assert heated_slug.potency is not None
    assert heated_slug.potency.base == 140
    assert heated_slug.potency.combo is not None
    assert heated_slug.potency.combo.potency == 320
    assert heated_slug.potency.combo.previous_actions == ("Heated Split Shot",)

    reassemble = next(action for action in actions if action.name == "Reassemble")
    assert reassemble.potency is None


def test_rejects_unknown_potency_wording() -> None:
    html = replace_action_text(
        "Drill",
        "Delivers an attack with a potency of 660.",
        "Damage varies according to an unusual potency formula.",
    )

    with pytest.raises(JobGuideParseError, match="Unsupported potency wording for 'Drill'"):
        parse_job_actions(html)


def test_parses_aoe_falloff() -> None:
    actions = parse_job_actions(load_full_guide())

    chain_saw = next(action for action in actions if action.name == "Chain Saw")
    assert chain_saw.name == "Chain Saw"
    assert chain_saw.potency is not None
    assert chain_saw.potency.base == 660
    assert chain_saw.potency.combo is None
    assert chain_saw.potency.falloff is not None
    assert chain_saw.potency.falloff.additional_target_multiplier == 0.75


def test_rejects_unrecognized_aoe_falloff_wording() -> None:
    html = replace_action_text(
        "Chain Saw",
        "25% less for all remaining enemies",
        "reduced damage to every enemy after the first",
    )

    with pytest.raises(JobGuideParseError, match="Unsupported AoE falloff wording"):
        parse_job_actions(html)


def test_parses_initial_and_damage_over_time_potency() -> None:
    actions = parse_job_actions(load_full_guide())

    bioblaster = next(action for action in actions if action.name == "Bioblaster")
    assert bioblaster.name == "Bioblaster"
    assert bioblaster.potency is not None
    assert bioblaster.potency.base == 50
    assert bioblaster.potency.damage_over_time is not None
    assert bioblaster.potency.damage_over_time.potency_per_tick == 50
    assert bioblaster.potency.damage_over_time.duration_seconds == 15


def test_rejects_incomplete_damage_over_time_effect() -> None:
    html = replace_action_text("Bioblaster", "Duration: 15s<br>", "")

    with pytest.raises(JobGuideParseError, match="Incomplete damage-over-time effect"):
        parse_job_actions(html)


def test_rejects_html_without_action_rows() -> None:
    with pytest.raises(JobGuideParseError, match="No job-action rows found"):
        parse_job_actions("<html><body></body></html>")


def test_missing_description_is_not_taken_from_a_later_row() -> None:
    html = (
        '<tr id="pve_action__1">'
        '<td class="skill"><strong>Drill</strong></td>'
        '<td class="jobclass">Lv. 58</td>'
        '<td class="classification">Weaponskill</td></tr>'
        '<tr><td class="content">Delivers an attack with a potency of 660.</td></tr>'
    )
    with pytest.raises(JobGuideParseError, match="missing required cells"):
        parse_job_actions(html)
