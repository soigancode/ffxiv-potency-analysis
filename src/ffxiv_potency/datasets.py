"""Independent action, gear and pet datasets with checked patch applicability."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jobs import job_code
from .patches import KNOWN_PATCHES, LATEST_KNOWN_PATCH, patch_order, played_patch
from .reference_data import reference_path


def validate_manifest(document: dict[str, Any], root: Path) -> None:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("unsupported dataset manifest schema")
    if "support" in document:
        support = document["support"]
        if not isinstance(support, dict) or type(support.get("level")) is not int:
            raise ValueError("invalid manifest support conditions")
        for key in ("valid_from", "valid_until"):
            if support.get(key) not in KNOWN_PATCHES:
                raise ValueError("invalid support patch boundary")
        if patch_order(support["valid_from"]) >= patch_order(support["valid_until"]):
            raise ValueError("invalid support patch range")
        if not isinstance(support.get("played_patches"), list) or any(
            patch not in KNOWN_PATCHES for patch in support["played_patches"]
        ):
            raise ValueError("invalid supported played patches")
        if not isinstance(support.get("encounters"), list) or any(
            type(encounter) is not int for encounter in support["encounters"]
        ):
            raise ValueError("invalid supported encounters")
    for category in ("action_sets", "gear_sets", "pet_scaling_sets"):
        rows = document.get(category)
        if not isinstance(rows, list):
            raise ValueError(f"manifest is missing {category}")  # noqa: TRY004
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key]
                                              for key in ("id", "file", "valid_from", "verified_through")):
                raise ValueError(f"invalid {category} entry")
            for key in ("valid_from", "valid_until", "verified_through"):
                if row.get(key) is not None:
                    patch_order(row[key])
                    if row[key] not in KNOWN_PATCHES:
                        raise ValueError(f"unknown patch label {row[key]!r}")
        ids = set()
        previous_end = None
        for index, row in enumerate(sorted(rows, key=lambda item: patch_order(item["valid_from"]))):
            if row["id"] in ids:
                raise ValueError(f"duplicate {category} ID {row['id']}")
            ids.add(row["id"])
            start = patch_order(row["valid_from"])
            end = patch_order(row["valid_until"]) if row.get("valid_until") else None
            verified = patch_order(row["verified_through"])
            if end is not None and start >= end:
                raise ValueError(f"invalid range for {row['id']}")
            if verified < start:
                raise ValueError(f"invalid verification boundary for {row['id']}")
            if index and (previous_end is None or start < previous_end):
                raise ValueError(f"overlapping {category} ranges")
            previous_end = end
            path = root / row["file"]
            if Path(row["file"]).is_absolute() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError(f"missing or invalid dataset file: {row['file']}")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"dataset {row['id']} must be a JSON object")  # noqa: TRY004
            if category == "gear_sets":
                if data.get("id") != row["id"]:
                    raise ValueError(f"gear ID mismatch for {row['id']}")
                model = data.get("combat_profile")
                if not isinstance(model, str):
                    raise ValueError(f"gear {row['id']} is missing its combat model")
                model_path = root / model
                if not model_path.resolve().is_relative_to(root.resolve()) or not model_path.is_file():
                    raise ValueError(f"missing combat model for {row['id']}")
                for field, category_name in (("food", "food"), ("potion", "potions")):
                    item = data.get(field)
                    if not isinstance(item, str) or not item.startswith(category_name + "/") or ".." in Path(item).parts:
                        raise ValueError(f"invalid {field} reference for {row['id']}")
                    if not reference_path("consumables", item).is_file():
                        raise ValueError(f"missing {field} reference for {row['id']}")



def load_manifest(job: str) -> tuple[dict[str, Any], Path]:
    local = Path("data/jobs") / job_code(job) / "datasets.json"
    path = local if local.is_file() else reference_path("jobs", job_code(job), "datasets.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(document, path.parent)
    if not isinstance(document.get("job"), str) or job_code(document["job"]) != job_code(job):
        raise ValueError(f"dataset manifest does not match job {job}")
    return document, path.parent


def select_set(document: dict[str, Any], category: str, patch: str,
               selected: str | None = None) -> dict[str, Any]:
    rows = document[category]
    if selected is not None:
        matches = [row for row in rows if row["id"] == selected]
    else:
        point = patch_order(patch)
        matches = [row for row in rows if patch_order(row["valid_from"]) <= point
                   and (not row.get("valid_until") or point < patch_order(row["valid_until"]))]
    if len(matches) != 1:
        raise ValueError(f"no unique {category} dataset for patch {patch}" +
                         (f" and ID {selected!r}" if selected else ""))
    return matches[0]


@dataclass(frozen=True)
class DatasetSelection:
    patch: str
    patch_source: str
    actions: Path
    actions_since: str
    gear: Path
    gear_id: str
    gear_name: str
    gear_source: str
    pet_scaling: Path | None


def resolve_datasets(job: str, fight: dict[str, Any], *, gear: str | None = None) -> DatasetSelection:
    manifest, root = load_manifest(job)
    start, report = fight.get("startTime"), fight.get("reportStartTime")
    patch = played_patch(start + report) if isinstance(start, (int, float)) and isinstance(
        report, (int, float)) else None
    explicit = fight.get("playedPatch")
    if explicit is None and patch is None and isinstance(start, (int, float)) and isinstance(report, (int, float)):
        raise ValueError("fight predates the configured supported patch history")
    if explicit is not None:
        if not isinstance(explicit, str):
            raise ValueError("playedPatch must be a patch label")
        patch_order(explicit)
        patch = explicit
    source = "explicit played patch" if explicit else "fight date" if patch else "latest configured patch (date unavailable)"
    patch = patch or LATEST_KNOWN_PATCH
    support = manifest["support"]
    point = patch_order(patch)
    if patch not in support["played_patches"]:
        raise ValueError(f"{job} analysis is unsupported for played patch {patch}")
    if point < patch_order(support["valid_from"]) or point >= patch_order(support["valid_until"]):
        raise ValueError(f"{job} analysis is unsupported for played patch {patch}")
    encounter = fight.get("encounterID")
    if encounter is not None and encounter not in support["encounters"]:
        raise ValueError(f"{job} analysis is unsupported for encounter {encounter}")
    level = fight.get("level")
    if level is not None and level != support["level"]:
        raise ValueError(f"{job} analysis supports level {support['level']} only")
    if fight.get("itemLevelSync") or fight.get("levelSync"):
        raise ValueError("synced analysis is not supported")
    actions = select_set(manifest, "action_sets", patch)
    selected_gear = select_set(manifest, "gear_sets", patch, gear)
    gear_document = json.loads((root / selected_gear["file"]).read_text())
    if gear_document.get("level") != support["level"]:
        raise ValueError("gear dataset has unsupported level")
    if gear_document.get("id") != selected_gear["id"]:
        raise ValueError("gear dataset ID does not match its manifest")
    for category, field in (("food", "food"), ("potions", "potion")):
        item = gear_document.get(field)
        if not isinstance(item, str) or not item.startswith(category + "/") or ".." in Path(item).parts:
            raise ValueError(f"invalid {field} reference")
        consumable = json.loads(reference_path("consumables", item).read_text())
        if patch_order(consumable["introduced_patch"]) > point:
            raise ValueError(f"{field} was not available in patch {patch}")
    pets = select_set(manifest, "pet_scaling_sets", patch) if manifest["pet_scaling_sets"] else None
    return DatasetSelection(patch, source, root / actions["file"], actions["valid_from"],
                            root / selected_gear["file"], selected_gear["id"],
                            selected_gear["name"], "user-selected" if gear else "assumed",
                            root / pets["file"] if pets else None)
