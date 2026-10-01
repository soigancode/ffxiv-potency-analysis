"""Tests for clear behavior."""

from pathlib import Path

from ffxiv_potency import cli


def test_clear_logs_requires_confirmation_and_keeps_job_snapshots(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    logs = tmp_path / "data/logs"
    saved = logs / "report/fight-1/source-2/fight.json"
    saved.parent.mkdir(parents=True)
    saved.write_text("{}", encoding="utf-8")
    actions = tmp_path / "data/jobs/brd/7.4/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert cli.main(["clear", "logs"]) == 0
    assert saved.exists()
    assert "Cancelled." in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    assert cli.main(["clear", "logs"]) == 0
    assert logs.is_dir() and not any(logs.iterdir())
    assert actions.exists()



def test_clear_logs_yes_supports_custom_download_directory(tmp_path: Path) -> None:
    logs = tmp_path / "downloads"
    logs.mkdir()
    (logs / "fight.json").write_text("{}", encoding="utf-8")
    assert cli.main(["clear", "logs", "--output", str(logs), "--yes"]) == 0
    assert not any(logs.iterdir())



def test_clear_cache_preserves_logs_and_checks_confirmation(tmp_path, monkeypatch) -> None:
    log = tmp_path / "downloads/report/fight-1/source-2"
    log.mkdir(parents=True)
    cache = tmp_path / "analysis-cache/report/fight-1/source-2.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}")
    fight = log / "fight.json"
    fight.write_text("{}")
    args = ["clear", "cache", "--output", str(tmp_path / "downloads")]
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert cli.main(args) == 0
    assert cache.exists()
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert cli.main(args) == 0
    assert not cache.exists()
    assert fight.exists()
    assert cli.main(args + ["--yes"]) == 0


def test_plain_clear_removes_logs_and_cache(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "fight.json").write_text("{}")
    cache = tmp_path / "analysis-cache/source-2.json"
    cache.parent.mkdir()
    cache.write_text("{}")
    assert cli.main(["clear", "--output", str(logs), "--yes"]) == 0
    assert not any(logs.iterdir())
    assert not cache.exists()


def test_clear_cache_does_not_follow_directory_symlinks(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    cache = outside / "analysis-cache.json"
    cache.write_text("{}")
    (logs / "linked-report").symlink_to(outside, target_is_directory=True)
    assert cli.main(["clear", "cache", "--output", str(logs), "--yes"]) == 0
    assert cache.exists()
