from pathlib import Path

import pytest

from ffxiv_potency.jobguide import JobGuideParseError, parse_job_actions

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parses_drill() -> None:
    actions = parse_job_actions(load_fixture("machinist_drill.html"))

    assert len(actions) == 1
    drill = actions[0]
    assert drill.name == "Drill"
    assert drill.level == 58
    assert drill.action_type == "Weaponskill"
    assert drill.potency is not None
    assert drill.potency.base == 660
    assert drill.potency.combo is None
    assert "Maximum Charges: 2" in drill.description


def test_parses_combo_potency_and_non_damaging_action() -> None:
    actions = parse_job_actions(load_fixture("machinist_combo.html"))

    heated_slug = next(action for action in actions if action.name == "Heated Slug Shot")
    assert heated_slug.potency is not None
    assert heated_slug.potency.base == 140
    assert heated_slug.potency.combo is not None
    assert heated_slug.potency.combo.potency == 320
    assert heated_slug.potency.combo.previous_actions == ("Heated Split Shot",)

    reassemble = next(action for action in actions if action.name == "Reassemble")
    assert reassemble.potency is None


def test_rejects_unknown_potency_wording() -> None:
    html = load_fixture("machinist_drill.html").replace(
        "Delivers an attack with a potency of 660.",
        "Damage varies according to an unusual potency formula.",
    )

    with pytest.raises(JobGuideParseError, match="Unsupported potency wording for 'Drill'"):
        parse_job_actions(html)


def test_parses_aoe_falloff() -> None:
    actions = parse_job_actions(load_fixture("machinist_chain_saw.html"))

    assert len(actions) == 1
    chain_saw = actions[0]
    assert chain_saw.name == "Chain Saw"
    assert chain_saw.potency is not None
    assert chain_saw.potency.base == 660
    assert chain_saw.potency.combo is None
    assert chain_saw.potency.falloff is not None
    assert chain_saw.potency.falloff.additional_target_multiplier == 0.75


def test_rejects_unrecognized_aoe_falloff_wording() -> None:
    html = load_fixture("machinist_chain_saw.html").replace(
        "25% less for all remaining enemies",
        "reduced damage to every enemy after the first",
    )

    with pytest.raises(JobGuideParseError, match="Unsupported AoE falloff wording"):
        parse_job_actions(html)


def test_parses_initial_and_damage_over_time_potency() -> None:
    actions = parse_job_actions(load_fixture("machinist_bioblaster.html"))

    assert len(actions) == 1
    bioblaster = actions[0]
    assert bioblaster.name == "Bioblaster"
    assert bioblaster.potency is not None
    assert bioblaster.potency.base == 50
    assert bioblaster.potency.damage_over_time is not None
    assert bioblaster.potency.damage_over_time.potency_per_tick == 50
    assert bioblaster.potency.damage_over_time.duration_seconds == 15


def test_rejects_incomplete_damage_over_time_effect() -> None:
    html = load_fixture("machinist_bioblaster.html").replace("Duration: 15s<br>", "")

    with pytest.raises(JobGuideParseError, match="Incomplete damage-over-time effect"):
        parse_job_actions(html)


def test_rejects_html_without_action_rows() -> None:
    with pytest.raises(JobGuideParseError, match="No job-action rows found"):
        parse_job_actions("<html><body></body></html>")
