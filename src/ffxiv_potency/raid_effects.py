"""Versioned raid effects and references to parsed job actions."""

import json
import re
from pathlib import Path
from typing import Any

from .datasets import job_code, select_set, validate_manifest
from .reference_data import reference_path

EFFECT_JOBS = {
    "scholar": ("Chain Stratagem",),
    "dragoon": ("Battle Litany",),
    "bard": ("Battle Voice", "Army's Paeon", "The Wanderer's Minuet"),
    "dancer": ("Devilment",),
}
RATE_PATTERN = re.compile(
    r"(?:(critical|direct) hit rate|rate at which target takes (critical) hits)[^.%]*? by (\d+)%",
    re.IGNORECASE,
)
REQUIRED_EFFECTS = {(action, rate) for job, actions in EFFECT_JOBS.items()
                    for action in actions
                    for rate in (("critical", "direct") if job == "dancer" else
                                 ("critical",) if action in {"Chain Stratagem", "Battle Litany", "The Wanderer's Minuet"}
                                 else ("direct",))}


def description_effects(action: str, description: str, job: str) -> list[dict[str, Any]]:
    if action == "Devilment":
        rates = set(re.findall(r"(critical|direct) hit rate", description, re.IGNORECASE))
        bonuses = re.findall(r"\bby (\d+)%", description, re.IGNORECASE)
        if {rate.casefold() for rate in rates} != {"critical", "direct"} or len(bonuses) != 1:
            raise ValueError(f"expected both crit and DH rates for {action!r}")
        parsed = [(rate, int(bonuses[0]) / 100) for rate in ("critical", "direct")]
    else:
        matches = list(RATE_PATTERN.finditer(description))
        if len(matches) != 1:
            raise ValueError(f"expected one crit/DH rate for {action!r}, found {len(matches)}")
        match = matches[0]
        kind = "critical" if "critical" in match.group(0).casefold() else "direct"
        parsed = [(kind, int(match.group(3)) / 100)]
    return [{"action": action, "status": action, "job": job,
             "target": "enemy" if action == "Chain Stratagem" else "player",
             "rate": kind, "bonus": bonus} for kind, bonus in parsed]


def job_action_path(data_root: Path, job: str, patch: str) -> Path | None:
    local = data_root / "jobs" / job_code(job) / "datasets.json"
    path = local if local.is_file() else reference_path("jobs", job_code(job), "datasets.json")
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text())
    validate_manifest(manifest, path.parent)
    if manifest.get("job") != job:
        raise ValueError(f"raid-effect job manifest does not match {job}")
    return path.parent / select_set(manifest, "action_sets", patch)["file"]


def action_effects(path: Path, job: str) -> list[dict[str, Any]]:
    document = json.loads(path.read_text())
    result = []
    for name in EFFECT_JOBS[job]:
        actions = [row for row in document["actions"] if row.get("name") == name]
        if len(actions) != 1:
            raise ValueError(f"expected one parsed action for {name!r}")
        result.extend(description_effects(name, " ".join(actions[0]["description"]), job))
    return result


def resolve_effects(document: dict[str, Any], data_root: Path, patch: str) -> list[dict[str, Any]]:
    rows = document.get("effects")
    if not isinstance(rows, list):
        raise TypeError("raid-effect snapshot must contain all configured crit/DH effects")
    resolved = []
    jobs: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("job") not in EFFECT_JOBS:
            raise ValueError("invalid raid-effect entry")
        effect = dict(row)
        source = effect.pop("source", None)
        if source not in (None, "job_actions"):
            raise ValueError("unsupported raid-effect source")
        if source == "job_actions":
            if "bonus" in effect:
                raise ValueError("job action references must not duplicate a bonus")
            job = effect["job"]
            if job not in jobs:
                path = job_action_path(data_root, job, patch)
                if path is None:
                    raise ValueError(f"missing parsed action data for raid-effect job {job}")
                jobs[job] = action_effects(path, job)
            candidates = [item for item in jobs[job]
                          if item["action"] == effect.get("action") and item["rate"] == effect.get("rate")]
            if len(candidates) != 1:
                raise ValueError("raid-effect reference does not match the parsed action")
            effect["bonus"] = candidates[0]["bonus"]
        bonus = effect.get("bonus")
        if (not isinstance(bonus, (int, float)) or isinstance(bonus, bool) or not 0 <= bonus <= 1
                or effect.get("action") not in EFFECT_JOBS[effect["job"]]
                or effect.get("status") != effect.get("action")
                or effect.get("target") != ("enemy" if effect.get("action") == "Chain Stratagem" else "player")):
            raise ValueError("invalid raid-effect entry")
        resolved.append(effect)
    if len(resolved) != len(REQUIRED_EFFECTS) or {
        (row.get("action"), row.get("rate")) for row in resolved
    } != REQUIRED_EFFECTS:
        raise ValueError("raid-effect snapshot must contain all configured crit/DH effects")
    return resolved


def validate_effect_manifest(
    document: dict[str, Any], root: Path, *, data_root: Path | None = None,
) -> None:
    validate_manifest({"schema_version": document.get("schema_version"),
                       "action_sets": document.get("effect_sets"), "gear_sets": [],
                       "pet_scaling_sets": []}, root)
    for row in document["effect_sets"]:
        data = json.loads((root / row["file"]).read_text())
        if data.get("patch") != row["valid_from"]:
            raise ValueError("raid-effect snapshot patch does not match its validity range")
        resolve_effects(data, data_root or root.parent, row["valid_from"])


def select_effect_document(data_root: Path, patch: str) -> dict[str, Any]:
    local = data_root / "raid_effects/datasets.json"
    path = local if local.is_file() else reference_path("raid_effects", "datasets.json")
    manifest = json.loads(path.read_text())
    validate_effect_manifest(manifest, path.parent)
    row = select_set(manifest, "effect_sets", patch)
    return json.loads((path.parent / row["file"]).read_text())
