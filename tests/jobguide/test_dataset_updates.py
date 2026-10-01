"""Job-guide updates retain unchanged datasets and publish only valid changes."""

import json
import shutil
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.jobguide.snapshot import update_job_guide

FIXTURE = Path(__file__).parents[1] / "fixtures/jobguide/mch_full_7_5.html"


def test_unchanged_guide_keeps_original_actions_and_records_capture(tmp_path) -> None:
    root = tmp_path / "jobs/mch"
    shutil.copytree(Path("data/jobs/mch"), root)
    original = (root / "7.4/actions.json").read_bytes()
    result = update_job_guide(job="machinist", patch="7.56", output_root=tmp_path,
                              transport=httpx.MockTransport(lambda _: httpx.Response(200, text=FIXTURE.read_text())))
    assert result.actions == root / "7.4/actions.json"
    assert result.actions.read_bytes() == original
    assert not (root / "7.56/actions.json").exists()
    manifest = json.loads((root / "datasets.json").read_text())
    assert len(manifest["action_sets"]) == 1
    assert manifest["last_capture"]["patch"] == "7.56"


def test_changed_guide_closes_previous_range(tmp_path) -> None:
    root = tmp_path / "jobs/mch"
    shutil.copytree(Path("data/jobs/mch"), root)
    html = FIXTURE.read_text()
    # Change an action's potency while retaining supported wording.
    changed = html.replace("potency of 660.", "potency of 670.", 1)
    assert changed != html
    result = update_job_guide(job="machinist", patch="7.56", output_root=tmp_path,
                              transport=httpx.MockTransport(lambda _: httpx.Response(200, text=changed)))
    assert result.actions == root / "7.56/actions.json"
    rows = json.loads((root / "datasets.json").read_text())["action_sets"]
    assert rows[0]["valid_until"] == "7.56"
    assert rows[1]["valid_from"] == "7.56"
    assert (root / "7.4/actions.json").exists()


def test_bad_existing_manifest_is_not_overwritten(tmp_path) -> None:
    root = tmp_path / "jobs/mch"
    shutil.copytree(Path("data/jobs/mch"), root)
    path = root / "datasets.json"
    data = json.loads(path.read_text())
    data["gear_sets"][0]["valid_until"] = "8.0"
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    with pytest.raises(ValueError, match="overlapping"):
        update_job_guide(job="machinist", patch="7.56", output_root=tmp_path,
                          transport=httpx.MockTransport(lambda _: httpx.Response(200, text=FIXTURE.read_text())))
    assert path.read_bytes() == original


def test_successive_unchanged_patches_extend_verification(tmp_path, monkeypatch) -> None:
    from ffxiv_potency.jobguide import snapshot

    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=FIXTURE.read_text()))
    monkeypatch.setattr(snapshot, "LATEST_KNOWN_PATCH", "7.4")
    first = update_job_guide(job="machinist", patch="7.4", output_root=tmp_path, transport=transport)
    original = first.actions.read_bytes()
    monkeypatch.setattr(snapshot, "LATEST_KNOWN_PATCH", "7.45")
    second = update_job_guide(job="machinist", patch="7.45", output_root=tmp_path, transport=transport)
    assert second.actions == first.actions
    assert second.actions.read_bytes() == original
    rows = json.loads((tmp_path / "jobs/mch/datasets.json").read_text())["action_sets"]
    assert len(rows) == 1
    assert rows[0]["valid_from"] == "7.4"
    assert rows[0]["verified_through"] == "7.45"
    assert not (tmp_path / "jobs/mch/7.45/actions.json").exists()
