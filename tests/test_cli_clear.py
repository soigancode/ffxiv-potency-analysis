"""Clearing calculations independently from downloaded logs."""

from pathlib import Path

from ffxiv_potency import cli


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
