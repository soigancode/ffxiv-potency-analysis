"""Load shared patch labels and UTC release boundaries."""

import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path


def _load_patch_data() -> tuple[str, dict[str, datetime]]:
    checkout = Path(__file__).resolve().parents[2] / "data" / "patches.json"
    resource = checkout if checkout.is_file() else files("ffxiv_potency").joinpath(
        "data", "patches.json"
    )
    data = json.loads(resource.read_text(encoding="utf-8"))
    latest = data.get("latest_known_patch")
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
    return latest, dates


LATEST_KNOWN_PATCH, PATCH_STARTS = _load_patch_data()
