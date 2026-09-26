"""Download and export versioned job-guide snapshots."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .export import export_actions
from .fetch import fetch_job_guide
from .parse import parse_job_actions

MACHINIST_URL = "https://eu.finalfantasyxiv.com/jobguide/machinist/"
LATEST_KNOWN_PATCH = "7.55"


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """Files and action count produced by one update."""

    source: Path
    actions: Path
    action_count: int


def update_job_guide(
    *,
    job: str,
    patch: str,
    output_root: Path,
    url: str = MACHINIST_URL,
    transport: httpx.BaseTransport | None = None,
    retrieved_at: datetime | None = None,
) -> SnapshotResult:
    """Download, strictly parse, and export one versioned job-guide snapshot."""

    normalized_job = job.casefold()
    if normalized_job != "machinist":
        raise ValueError(f"unsupported job: {job!r}; currently only 'machinist' is supported")
    if patch != LATEST_KNOWN_PATCH:
        raise ValueError(
            f"only patch {LATEST_KNOWN_PATCH} is supported for now; received {patch!r}"
        )

    timestamp = retrieved_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone")

    snapshot_directory = output_root / normalized_job / patch
    source_path = snapshot_directory / "source.html"
    actions_path = snapshot_directory / "actions.json"

    fetch_job_guide(url, source_path, transport=transport)
    source_bytes = source_path.read_bytes()
    html = source_bytes.decode("utf-8")
    actions = parse_job_actions(html)
    export_actions(
        actions,
        actions_path,
        job=normalized_job,
        patch=patch,
        source_url=url,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        retrieved_at=timestamp,
    )
    return SnapshotResult(source=source_path, actions=actions_path, action_count=len(actions))
