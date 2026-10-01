"""Download and export versioned job-guide snapshots."""

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ..datasets import job_code, validate_manifest
from ..patches import LATEST_KNOWN_PATCH, patch_order
from ..reference_data import reference_path
from .export import export_actions
from .fetch import fetch_job_guide
from .parse import parse_job_actions, parse_job_traits

JOBGUIDE_URL_TEMPLATE = "https://eu.finalfantasyxiv.com/jobguide/{job}/"
BRD_URL = JOBGUIDE_URL_TEMPLATE.format(job="bard")
MCH_URL = JOBGUIDE_URL_TEMPLATE.format(job="machinist")
JOBGUIDE_URLS = {"bard": BRD_URL, "machinist": MCH_URL}


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

    jobs_root = output_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    destination = jobs_root / job_code(normalized_job)
    with tempfile.TemporaryDirectory(dir=jobs_root, prefix=".jobguide-") as staging:
        staged = Path(staging) / "job"
        if destination.exists():
            shutil.copytree(destination, staged)
        else:
            seed = reference_path("jobs", job_code(normalized_job), "datasets.json")
            if seed.is_file():
                shutil.copytree(seed.parent, staged)
                initial = json.loads((staged / "datasets.json").read_text())
                for row in initial["action_sets"]:
                    (staged / row["file"]).unlink(missing_ok=True)
                initial["action_sets"] = []
                (staged / "datasets.json").write_text(json.dumps(initial))
            else:
                staged.mkdir()
        snapshot_directory = staged / patch
        source_path = snapshot_directory / "source.html"
        url = url or JOBGUIDE_URLS[normalized_job]
        fetch_job_guide(url, source_path, transport=transport)
        source_bytes = source_path.read_bytes()
        actions = parse_job_actions(source_bytes.decode("utf-8"))
        traits = parse_job_traits(source_bytes.decode("utf-8"))
        candidate = staged / "candidate.json"
        export_actions(actions, candidate, traits=traits, job=normalized_job, patch=patch,
                       source_url=url, source_sha256=hashlib.sha256(source_bytes).hexdigest(),
                       retrieved_at=timestamp)
        document = json.loads(candidate.read_text())
        manifest_path = staged / "datasets.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            validate_manifest(manifest, staged)
        else:
            manifest = {"schema_version": 1, "job": normalized_job, "action_sets": [],
                        "gear_sets": [], "pet_scaling_sets": []}
        rows = manifest["action_sets"]
        latest = max(rows, key=lambda row: patch_order(row["valid_from"])) if rows else None
        if latest and patch_order(patch) < patch_order(latest["verified_through"]):
            raise ValueError("cannot update a live job guide into an older verified patch")
        def content(value: dict) -> str:
            return json.dumps({key: sorted(value[key], key=lambda row: (row["name"], row.get("level", 0)))
                               for key in ("actions", "traits")}, sort_keys=True)
        unchanged = latest and content(json.loads((staged / latest["file"]).read_text())) == content(document)
        if unchanged and latest is not None:
            latest["verified_through"] = patch
            action_file = latest["file"]
        else:
            action_file = f"{patch}/actions.json"
            if latest and latest["valid_from"] != patch:
                latest["valid_until"] = patch
            if latest and latest["valid_from"] == patch:
                latest["verified_through"] = patch
            else:
                rows.append({"id": "actions_" + patch.replace(".", "_"), "file": action_file,
                             "valid_from": patch, "verified_through": patch})
            target = staged / action_file
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(candidate, target)
        candidate.unlink(missing_ok=True)
        manifest["last_capture"] = {"patch": patch, "source": document["source"]}
        validate_manifest(manifest, staged)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        backup = Path(staging) / "backup"
        if destination.exists():
            os.replace(destination, backup)
        try:
            os.replace(staged, destination)
        except OSError:
            if backup.exists():
                os.replace(backup, destination)
            raise
    return SnapshotResult(source=destination / patch / "source.html",
                          actions=destination / action_file, action_count=len(actions))
