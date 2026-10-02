"""Warrior guide coverage, historical reconstruction, and stable refreshes."""

import json
import shutil
from pathlib import Path

import httpx

from ffxiv_potency.jobguide import inspect_job_actions, parse_job_traits
from ffxiv_potency.jobguide.snapshot import update_job_guide

GUIDE = Path("tests/fixtures/jobguide/war_full_7_56.html")


def test_warrior_actions_and_traits_match_current_guide():
    report = inspect_job_actions(GUIDE.read_text())
    snapshot = json.loads(Path("data/jobs/war/7.5/actions.json").read_text())
    assert report.issues == ()
    assert report.source_action_count == len(report.actions) == 33
    assert [action.to_dict() for action in report.actions] == snapshot["actions"]
    traits = parse_job_traits(GUIDE.read_text())
    assert len(traits) == 19
    assert [trait.to_dict() for trait in traits] == snapshot["traits"]
    actions = {action.name: action.to_dict() for action in report.actions}
    assert actions["Damnation"]["potency"]["base"] == 55
    assert actions["Vengeance"]["potency"]["base"] == 55
    assert actions["Primal Rend"]["potency"]["falloff"]["additional_target_multiplier"] == 0.5
    assert actions["Equilibrium"]["potency"] is None
    assert "Tank Mastery" in {trait.name for trait in traits}
    assert "Increases the potency of Heavy Swing to 240" in " ".join(
        next(trait for trait in traits if trait.name == "Melee Mastery II").description
    )


def test_historical_snapshot_changes_only_the_three_documented_potencies():
    old = json.loads(Path("data/jobs/war/7.4/actions.json").read_text())
    current = json.loads(Path("data/jobs/war/7.5/actions.json").read_text())
    assert old["traits"] == current["traits"]
    assert old["source"]["reconstruction"]["restored_potencies"] == {
        "Inner Chaos": 660,
        "Primal Rend": 700,
        "Primal Ruination": 780,
    }
    assert [action["name"] for action in old["actions"]] == [
        action["name"] for action in current["actions"]
    ]
    for before, after in zip(old["actions"], current["actions"], strict=True):
        name = before["name"]
        if name in old["source"]["reconstruction"]["restored_potencies"]:
            value = old["source"]["reconstruction"]["restored_potencies"][name]
            new_value = after["potency"]["base"]
            before["potency"]["base"] = new_value
            before["description"] = [
                line.replace(f"potency of {value}", f"potency of {new_value}")
                for line in before["description"]
            ]
        assert before == after


def test_guide_refresh_preserves_both_warrior_action_versions(tmp_path):
    root = tmp_path / "data"
    shutil.copytree("data/jobs/war", root / "jobs/war")
    paths = [root / "jobs/war" / patch / "actions.json" for patch in ("7.4", "7.5")]
    before = [path.read_bytes() for path in paths]
    result = update_job_guide(
        job="warrior",
        patch="7.56",
        output_root=root,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=GUIDE.read_text())),
    )
    assert result.actions == paths[1]
    assert result.action_count == 33
    assert [path.read_bytes() for path in paths] == before
    manifest = json.loads((root / "jobs/war/datasets.json").read_text())
    assert manifest["last_capture"]["patch"] == "7.56"
    assert not (root / "jobs/war/7.56/actions.json").exists()
