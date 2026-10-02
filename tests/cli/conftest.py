"""Reusable saved Warrior sources for command-level integration checks."""

import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest


@pytest.fixture
def war_saved_sources(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "data/jobs/war", tmp_path / "data/jobs/war")
    logs = tmp_path / "data/logs"
    with ZipFile(root / "tests/fixtures/logs/war_vamp_fatale.zip") as archive:
        for member in archive.namelist():
            path = logs / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(member))
    monkeypatch.chdir(tmp_path)
    return sorted(logs.glob("*/fight-*/source-*"))
