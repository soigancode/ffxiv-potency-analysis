"""Load shared patch labels and UTC release boundaries."""

import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path


def _load_patch_data() -> tuple[str, dict[str, datetime], frozenset[str]]:
    checkout = Path(__file__).resolve().parents[2] / "data" / "patches.json"
    resource = checkout if checkout.is_file() else files("ffxiv_potency").joinpath(
        "data", "patches.json"
    )
    data = json.loads(resource.read_text(encoding="utf-8"))
    latest = data.get("latest_jobguide_patch", data.get("latest_known_patch"))
    starts = data.get("starts")
    if not isinstance(latest, str) or not latest:
        raise ValueError("patches.json must define a nonempty latest_known_patch")
    if not isinstance(starts, dict) or not starts:
        raise ValueError("patches.json must define patch start times")
    dates = {}
    for patch, start in starts.items():
        if not isinstance(patch, str) or not isinstance(start, str):
            raise TypeError("patch labels and start times must be strings")
        date = datetime.fromisoformat(start)
        if date.tzinfo is None or date.utcoffset() != UTC.utcoffset(date):
            raise ValueError(f"patch {patch} start time must include the UTC timezone")
        dates[patch] = date
    boundaries = data.get("known_boundaries", [])
    if not isinstance(boundaries, list) or any(not isinstance(value, str) for value in boundaries):
        raise ValueError("known patch boundaries must be labels")
    return latest, dates, frozenset([latest, *dates, *boundaries])


LATEST_KNOWN_PATCH, PATCH_STARTS, KNOWN_PATCHES = _load_patch_data()


def patch_order(patch: str) -> tuple[int, int]:
    """Compare FFXIV patch labels without float or lexical rounding."""
    import re

    if not isinstance(patch, str):
        raise ValueError("patch labels must be strings")  # noqa: TRY004
    match = re.fullmatch(r"(\d+)\.(\d{1,2})", patch)
    if match is None:
        raise ValueError(f"invalid patch label {patch!r}")
    return int(match[1]), int(match[2].ljust(2, "0"))


def played_patch(timestamp_ms: float) -> str | None:
    """Identify the finest configured release boundary for a UTC fight date."""
    eligible = [(date, patch) for patch, date in PATCH_STARTS.items()
                if timestamp_ms >= date.timestamp() * 1000]
    return max(eligible)[1] if eligible else None
