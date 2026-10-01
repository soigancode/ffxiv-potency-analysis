"""Tests for progress behavior."""

import io
from pathlib import Path

import pytest

from ffxiv_potency import cli


def test_progress_reuses_one_line_and_clears_it(monkeypatch, tmp_path: Path) -> None:

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal = Terminal()
    monkeypatch.setattr(cli.sys, "stderr", terminal)

    def fake_resolve(source: str, output: Path, *, announce: bool = True) -> Path:
        assert not announce
        return tmp_path / source

    def fake_compare(directories, actions, progress) -> None:
        assert directories == [tmp_path / "first", tmp_path / "second"]
        progress.update("Calculating", 0, 2)
        progress.update("Calculating", 1, 2)
        progress.update("Calculating", 2, 2)
        progress.clear()

    monkeypatch.setattr(cli, "_resolve_analysis_directory", fake_resolve)
    monkeypatch.setattr(cli, "_compare_directories", fake_compare)
    with cli._Progress() as progress:
        progress.message("Processing...")
        cli._download_and_compare(["first", "second"], tmp_path, None, progress)

    output = terminal.getvalue()
    assert output.startswith("\rProcessing...")
    assert "Loading fight data: [--------------------] 0/2" in output
    assert "Loading fight data: [####################] 2/2" in output
    assert "Calculating: [####################] 2/2" in output
    assert "\n" not in output
    assert output.endswith("\r")
    assert output.rsplit("\r", 2)[-2].strip() == ""



def test_progress_clears_on_error(monkeypatch) -> None:

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal = Terminal()
    monkeypatch.setattr(cli.sys, "stderr", terminal)
    with pytest.raises(ValueError, match="download failed"), cli._Progress() as progress:
        progress.update("Downloading", 0, 10)
        raise ValueError("download failed")
    assert terminal.getvalue().rsplit("\r", 2)[-2].strip() == ""

