"""Shared patch metadata and packaged resource loading."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ffxiv_potency import patches


def test_shared_patch_boundaries() -> None:
    assert patches.LATEST_KNOWN_PATCH == "7.56"
    assert patches.PATCH_STARTS["7.45"] == datetime(2026, 3, 3, 10, tzinfo=UTC)


def test_packaged_patch_resource(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = tmp_path / "package"
    (package / "data").mkdir(parents=True)
    (package / "data/patches.json").write_text(json.dumps({
        "latest_known_patch": "7.55", "starts": {"7.5": "2026-04-28T10:00:00Z"},
    }))
    monkeypatch.setattr(patches, "__file__", str(tmp_path / "a/b/patches.py"))
    monkeypatch.setattr(patches, "files", lambda _: package)
    latest, dates, known = patches._load_patch_data()
    assert latest == "7.55"
    assert "7.55" in known
    assert dates["7.5"] == datetime(2026, 4, 28, 10, tzinfo=UTC)
    (package / "data/patches.json").write_text(json.dumps({
        "latest_known_patch": "7.55", "starts": {"7.5": "2026-04-28T10:00:00"},
    }))
    with pytest.raises(ValueError, match="UTC timezone"):
        patches._load_patch_data()
