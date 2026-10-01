"""Dancer guide coverage, step variants, traits, and safe refreshes."""

import json
import shutil
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.jobguide import (
    JobGuideParseError,
    inspect_job_actions,
    parse_job_actions,
    parse_job_traits,
)
from ffxiv_potency.jobguide.snapshot import update_job_guide

GUIDE = Path("tests/fixtures/jobguide/dnc_full_7_56.html")


def test_dancer_snapshot_covers_actions_steps_and_traits() -> None:
    html = GUIDE.read_text()
    report = inspect_job_actions(html)
    committed = json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())
    assert report.issues == ()
    assert report.source_action_count == 35
    assert len(report.actions) == 41
    assert [a.to_dict() for a in report.actions] == committed["actions"]
    traits = parse_job_traits(html)
    assert len(traits) == 16
    assert [t.to_dict() for t in traits] == committed["traits"]
    assert (
        next(t for t in traits if t.name == "Increased Action Damage II").action_damage_multiplier
        == 1.2
    )
    assert "Saber Dance to 540" in " ".join(
        next(t for t in traits if t.name == "Dynamic Dancer").description
    )
    actions = {a.name: a.to_dict() for a in report.actions}
    for name in ["Emboite", "Entrechat", "Jete", "Pirouette", "Curing Waltz", "Improvisation"]:
        assert actions[name]["potency"] is None
    for name, base in [
        ("Standard Finish", 360),
        ("Single Standard Finish", 540),
        ("Double Standard Finish", 850),
        ("Technical Finish", 350),
        ("Single Technical Finish", 540),
        ("Double Technical Finish", 720),
        ("Triple Technical Finish", 900),
        ("Quadruple Technical Finish", 1300),
    ]:
        assert actions[name]["potency"]["base"] == base
        assert actions[name]["potency"]["falloff"]["additional_target_multiplier"] == 0.4
    assert actions["Quadruple Technical Finish"]["completed_steps"] == 4
    assert actions["Starfall Dance"]["potency"]["falloff"]["additional_target_multiplier"] == 0.25
    assert actions["Dance of the Dawn"]["potency"]["base"] == 1000


@pytest.mark.parametrize(
    "original,replacement,error",
    [
        ("2 Steps: 850<br>", "", "Incomplete step potency"),
        ("4 Steps: 5%<br>", "", "Incomplete damage buff"),
        (
            "60% less for all remaining enemies",
            "less damage for remaining enemies",
            "Unsupported AoE",
        ),
    ],
)
def test_dancer_rejects_incomplete_rules(original, replacement, error) -> None:
    html = GUIDE.read_text()
    assert original in html
    with pytest.raises(JobGuideParseError, match=error):
        parse_job_actions(html.replace(original, replacement))


def test_dancer_refresh_retains_version_and_validates_before_replacing(tmp_path: Path) -> None:
    root = tmp_path / "data"
    shutil.copytree("data/jobs/dnc", root / "jobs/dnc")
    actions = root / "jobs/dnc/7.4/actions.json"
    original = actions.read_bytes()
    result = update_job_guide(
        job="dancer",
        patch="7.56",
        output_root=root,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=GUIDE.read_text())),
    )
    assert result.actions == actions
    assert result.action_count == 41
    assert actions.read_bytes() == original
    manifest = root / "jobs/dnc/datasets.json"
    previous = manifest.read_bytes()
    with pytest.raises(JobGuideParseError):
        update_job_guide(
            job="dancer",
            patch="7.56",
            output_root=root,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="broken guide")),
        )
    assert actions.read_bytes() == original
    assert manifest.read_bytes() == previous
