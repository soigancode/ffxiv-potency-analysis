"""Complete official PLD parsing and metadata-only refresh compatibility."""

import json
import shutil
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.jobguide import inspect_job_actions, parse_job_traits
from ffxiv_potency.jobguide.parse import JobGuideParseError, _combo_potency, _parse_potency
from ffxiv_potency.jobguide.snapshot import update_job_guide

GUIDE = Path("tests/fixtures/jobguide/pld_full_7_56.html")


def test_complete_guide_actions_traits_and_non_damaging_potencies():
    report = inspect_job_actions(GUIDE.read_text())
    snapshot = json.loads(Path("data/jobs/pld/7.4/actions.json").read_text())
    assert report.issues == ()
    assert report.source_action_count == len(report.actions) == 39
    assert [a.to_dict() for a in report.actions] == snapshot["actions"]
    assert len(snapshot["traits"]) == 20
    assert [t.to_dict() for t in parse_job_traits(GUIDE.read_text())] == snapshot["traits"]
    actions = {a.name: a.to_dict() for a in report.actions}
    for name in ("Guardian", "Clemency", "Holy Sheltron", "Divine Veil", "Intervention"):
        assert actions[name]["potency"] is None
    assert actions["Holy Spirit"]["potency"]["conditional_potencies"] == {"Divine Might": 500, "Requiescat": 700}
    assert actions["Holy Circle"]["potency"]["conditional_potencies"] == {"Divine Might": 250, "Requiescat": 350}
    for name, value in (("Blade of Faith", 760), ("Blade of Truth", 880), ("Blade of Valor", 1000)):
        assert actions[name]["potency"]["conditional_potencies"] == {"Requiescat": value}
        assert "combo" not in actions[name]["potency"]


def test_sequence_exception_keeps_validation_for_incomplete_combos():
    with pytest.raises(JobGuideParseError, match="Incomplete combo"):
        _combo_potency("Riot Blade", ("Combo Action: Fast Blade",))
    with pytest.raises(JobGuideParseError, match="Incomplete combo"):
        _combo_potency("Blade of Faith", ("Combo Action: Riot Blade",))
    with pytest.raises(JobGuideParseError, match="Missing base spell"):
        _parse_potency("Holy Spirit", ("Divine Might Potency: 500", "Requiescat Potency: 700"))
    with pytest.raises(JobGuideParseError, match="Duplicate conditional"):
        _parse_potency("Holy Spirit", ("Deals damage with a potency of 400.",
                                       "Divine Might Potency: 500", "Divine Might Potency: 500"))


def test_unchanged_refresh_retains_historical_action_file(tmp_path):
    root = tmp_path / "data"
    shutil.copytree("data/jobs/pld", root / "jobs/pld")
    path = root / "jobs/pld/7.4/actions.json"
    before = path.read_bytes()
    result = update_job_guide(job="paladin", patch="7.56", output_root=root,
                              transport=httpx.MockTransport(lambda _: httpx.Response(200, text=GUIDE.read_text())))
    assert result.actions == path and result.action_count == 39
    assert path.read_bytes() == before
    manifest = json.loads((root / "jobs/pld/datasets.json").read_text())
    assert manifest["last_capture"]["patch"] == "7.56"
    assert not (root / "jobs/pld/7.56/actions.json").exists()
