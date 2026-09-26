"""Shared setup for audited logs; expected calculations stay in each test."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from ffxiv_potency.jobguide import parse_job_actions

FIXTURES = Path(__file__).parent / "fixtures"
_LOG_FILES = {
    "fight": "fight.json",
    "master_data": "master-data.json",
    "cast_events": "cast-events.json",
    "damage_events": "damage-events.json",
    "buff_events": "buff-events.json",
    "rankings": "rankings.json",
}
_REQUIRED_FILES = {"fight.json", "master-data.json", "cast-events.json", "damage-events.json"}


@pytest.fixture(scope="session")
def machinist_action_json() -> str:
    html = (FIXTURES / "machinist_full_7_5.html").read_text(encoding="utf-8")
    return json.dumps(
        {
            "job": "machinist",
            "patch": "7.55",
            "actions": [action.to_dict() for action in parse_job_actions(html)],
        }
    )


@pytest.fixture
def machinist_actions(tmp_path: Path, machinist_action_json: str) -> Path:
    path = tmp_path / "actions.json"
    path.write_text(machinist_action_json, encoding="utf-8")
    return path


@pytest.fixture
def load_audit(tmp_path: Path) -> Callable[[str], dict[str, Any]]:
    """Write a curated event fixture in the downloader's file format."""

    def load(name: str) -> dict[str, Any]:
        source = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        for key, filename in _LOG_FILES.items():
            if filename in _REQUIRED_FILES or key in source:
                (tmp_path / filename).write_text(json.dumps(source[key]), encoding="utf-8")
        return source

    return load


@pytest.fixture
def extract_fight(tmp_path: Path) -> Callable[[str, str], None]:
    """Extract required fight files and any available buff/ranking records."""

    def extract(archive_name: str, prefix: str) -> None:
        with ZipFile(FIXTURES / archive_name) as archive:
            members = set(archive.namelist())
            for filename in _LOG_FILES.values():
                member = prefix + filename
                if filename in _REQUIRED_FILES or member in members:
                    (tmp_path / filename).write_bytes(archive.read(member))

    return extract
