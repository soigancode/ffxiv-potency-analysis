"""Download and export versioned job-guide snapshots."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ..patches import LATEST_KNOWN_PATCH
from .export import export_actions
from .fetch import fetch_job_guide
from .parse import parse_job_actions, parse_job_traits

JOBGUIDE_URL_TEMPLATE = "https://eu.finalfantasyxiv.com/jobguide/{job}/"
MACHINIST_URL = JOBGUIDE_URL_TEMPLATE.format(job="machinist")
BARD_URL = JOBGUIDE_URL_TEMPLATE.format(job="bard")
JOBGUIDE_URLS = {"machinist": MACHINIST_URL, "bard": BARD_URL}


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
    url: str | None = None,
    transport: httpx.BaseTransport | None = None,
    retrieved_at: datetime | None = None,
) -> SnapshotResult:
    """Download, strictly parse, and export one versioned job-guide snapshot."""

    normalized_job = job.casefold()
    if normalized_job not in JOBGUIDE_URLS:
        raise ValueError(f"unsupported job-guide job: {job!r}")
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

    url = url or JOBGUIDE_URLS[normalized_job]
    fetch_job_guide(url, source_path, transport=transport)
    source_bytes = source_path.read_bytes()
    html = source_bytes.decode("utf-8")
    actions = parse_job_actions(html)
    traits = parse_job_traits(html)
    export_actions(
        actions,
        actions_path,
        traits=traits,
        job=normalized_job,
        patch=patch,
        source_url=url,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        retrieved_at=timestamp,
    )
    return SnapshotResult(source=source_path, actions=actions_path, action_count=len(actions))
