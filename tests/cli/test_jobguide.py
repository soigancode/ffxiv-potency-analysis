"""Tests for jobguide behavior."""

from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.jobguide import SnapshotResult


@pytest.mark.parametrize("alias", ["machinist", "MACHINIST", "MCH", "mch"])
def test_cli_updates_mch_snapshot(monkeypatch, tmp_path: Path, capsys, alias: str) -> None:
    expected = SnapshotResult(
        source=tmp_path / "jobs" / "mch" / "7.56" / "source.html",
        actions=tmp_path / "jobs" / "mch" / "7.56" / "actions.json",
        action_count=40,
    )

    def fake_update_job_guide(**kwargs) -> SnapshotResult:
        assert kwargs["job"] == "machinist"
        assert kwargs["patch"] == "7.56"
        assert kwargs["output_root"] == tmp_path
        return expected

    monkeypatch.setattr(cli, "update_job_guide", fake_update_job_guide)

    exit_code = cli.main(["jobguide", alias, "--output", str(tmp_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"Saved source: {expected.source}" in output
    assert f"Wrote 40 actions: {expected.actions}" in output



@pytest.mark.parametrize("alias", ["bard", "BARD", "BRD", "brd"])
def test_cli_updates_brd_snapshot(monkeypatch, tmp_path: Path, capsys, alias: str) -> None:
    expected = SnapshotResult(
        source=tmp_path / "jobs/brd/7.56/source.html",
        actions=tmp_path / "jobs/brd/7.4/actions.json",
        action_count=34,
    )

    def fake_update_job_guide(**kwargs) -> SnapshotResult:
        assert kwargs["job"] == "bard"
        assert kwargs["output_root"] == tmp_path
        return expected

    monkeypatch.setattr(cli, "update_job_guide", fake_update_job_guide)
    assert cli.main(["jobguide", alias, "--output", str(tmp_path)]) == 0
    assert f"Wrote 34 actions: {expected.actions}" in capsys.readouterr().out



def test_cli_updates_raid_buffs_without_patch(monkeypatch, tmp_path: Path, capsys) -> None:
    expected = tmp_path / "raid_effects/7.56.json"

    def fake_update(output_root: Path) -> Path:
        assert output_root == tmp_path
        return expected

    monkeypatch.setattr(cli, "update_raid_effects", fake_update)
    assert cli.main(["jobguide", "BUFFS", "--output", str(tmp_path)]) == 0
    assert str(expected) in capsys.readouterr().out



def test_cli_jobguide_without_item_updates_all_jobs_and_buffs(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    updated: list[str] = []

    def fake_update_job_guide(**kwargs) -> SnapshotResult:
        job = kwargs["job"]
        assert kwargs["patch"] == "7.56"
        assert kwargs["output_root"] == tmp_path
        updated.append(job)
        return SnapshotResult(
            source=tmp_path / job / "source.html",
            actions=tmp_path / job / "actions.json",
            action_count=1,
        )

    def fake_update_raid_effects(output_root: Path) -> Path:
        assert output_root == tmp_path
        updated.append("buffs")
        return tmp_path / "raid_effects/7.56.json"

    monkeypatch.setattr(cli, "update_job_guide", fake_update_job_guide)
    monkeypatch.setattr(cli, "update_raid_effects", fake_update_raid_effects)

    assert cli.main(["jobguide", "--output", str(tmp_path)]) == 0
    assert updated == ["bard", "machinist", "dancer", "buffs"]
    output = capsys.readouterr().out
    assert output.count("Wrote 1 actions:") == 3
    assert "Saved raid effects:" in output
