"""Write normalized, versioned job-guide data as JSON."""

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import Action, Trait
from .parse import parse_job_actions, parse_job_traits


def export_actions(
    actions: list[Action],
    destination: Path,
    *,
    traits: list[Trait] | None = None,
    job: str,
    patch: str,
    source_url: str,
    source_sha256: str | None = None,
    retrieved_at: datetime | None = None,
) -> Path:
    """Write actions and provenance metadata to *destination*."""

    timestamp = retrieved_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone")

    source_metadata = {
        "url": source_url,
        "retrieved_at": timestamp.isoformat().replace("+00:00", "Z"),
    }
    if source_sha256 is not None:
        source_metadata["sha256"] = source_sha256

    document = {
        "schema_version": 3,
        "job": job,
        "patch": patch,
        "source": source_metadata,
        "actions": [action.to_dict() for action in actions],
        "traits": [trait.to_dict() for trait in traits] if traits is not None else [],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return destination


def import_saved_guide(
    source: Path,
    destination: Path,
    *,
    job: str,
    patch: str,
    source_url: str,
    retrieved_at: datetime | None = None,
) -> Path:
    """Parse a saved HTML snapshot and export normalized JSON."""

    html = source.read_text(encoding="utf-8")
    actions = parse_job_actions(html)
    traits = parse_job_traits(html)
    return export_actions(
        actions,
        destination,
        traits=traits,
        job=job,
        patch=patch,
        source_url=source_url,
        retrieved_at=retrieved_at,
    )
