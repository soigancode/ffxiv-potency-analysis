from pathlib import Path

from ffxiv_potency.jobguide import inspect_job_actions

FIXTURES = Path(__file__).parent / "fixtures"


def test_complete_machinist_snapshot_has_expected_coverage() -> None:
    html = (FIXTURES / "machinist_full_7_5.html").read_text(encoding="utf-8")

    report = inspect_job_actions(html)

    assert report.source_action_count == 39
    assert len(report.actions) == 40
    assert len(report.issues) == 0
    actions = {action.name: action for action in report.actions}
    assert len(actions) == len(report.actions)
    assert actions["Split Shot"].potency is not None
    assert actions["Split Shot"].potency.base == 140
    assert actions["Reassemble"].potency is None
