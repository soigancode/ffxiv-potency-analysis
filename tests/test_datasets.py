"""Independent patch boundaries, gear selection and manifest validation."""

import copy
from datetime import UTC, datetime

import pytest

from ffxiv_potency.datasets import load_manifest, resolve_datasets, select_set, validate_manifest
from ffxiv_potency.patches import patch_order


def fight(date: datetime) -> dict:
    return {"encounterID": 105, "startTime": 0, "reportStartTime": date.timestamp() * 1000}


@pytest.mark.parametrize("job", ["bard", "machinist"])
def test_gear_switches_at_relic_release(job: str) -> None:
    before = resolve_datasets(job, fight(datetime(2026, 7, 28, 9, 59, 59, tzinfo=UTC)))
    after = resolve_datasets(job, fight(datetime(2026, 7, 28, 10, tzinfo=UTC)))
    assert before.gear_id == "savage_7_4"
    assert after.gear_id == "relic_7_55"
    assert before.actions == after.actions
    assert before.actions_since == "7.4"
    assert after.patch == "7.55"
    override = resolve_datasets(job, fight(datetime(2026, 5, 1, tzinfo=UTC)), gear="relic_7_55")
    assert override.gear_source == "user-selected"
    assert override.gear_id == "relic_7_55"


@pytest.mark.parametrize("change,match", [
    ("overlap", "overlapping"), ("duplicate", "duplicate"), ("missing", "missing"),
    ("reverse", "invalid range"), ("gap", "no unique"),
])
def test_manifest_rejects_invalid_selection(change: str, match: str) -> None:
    manifest, root = load_manifest("machinist")
    document = copy.deepcopy(manifest)
    rows = document["gear_sets"]
    if change == "overlap":
        rows[0]["valid_until"] = "8.0"
    elif change == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif change == "missing":
        rows[0]["file"] = "missing.json"
    elif change == "reverse":
        rows[0]["valid_until"] = "7.4"
    else:
        rows[0]["valid_until"] = "7.45"
        rows[1]["valid_from"] = "7.55"
    with pytest.raises(ValueError, match=match):
        validate_manifest(document, root)
        select_set(document, "gear_sets", "7.5")


def test_old_actions_do_not_enable_new_expansion_or_sync() -> None:
    manifest, _ = load_manifest("machinist")
    with pytest.raises(ValueError, match="no unique"):
        select_set(manifest, "gear_sets", "8.0")
    value = fight(datetime(2026, 5, 1, tzinfo=UTC))
    value["level"] = 110
    with pytest.raises(ValueError, match="level 100"):
        resolve_datasets("machinist", value)
    value.pop("level")
    value["itemLevelSync"] = 700
    with pytest.raises(ValueError, match="synced"):
        resolve_datasets("machinist", value)


def test_patch_order_preserves_minor_patch_boundaries() -> None:
    assert patch_order("7.4") < patch_order("7.45") < patch_order("7.5") < patch_order("7.55")
    with pytest.raises(ValueError):
        patch_order("7.55/escape")


def test_known_actions_do_not_enable_unvalidated_played_patch() -> None:
    with pytest.raises(ValueError, match="unsupported for played patch 8.0"):
        resolve_datasets("machinist", {"playedPatch": "8.0", "encounterID": 105})
    with pytest.raises(ValueError, match="unsupported for played patch 7.58"):
        resolve_datasets("machinist", {"playedPatch": "7.58", "encounterID": 105})


def test_pre_supported_date_is_not_treated_as_missing_date() -> None:
    with pytest.raises(ValueError, match="predates"):
        resolve_datasets("machinist", fight(datetime(2025, 1, 1, tzinfo=UTC)))
