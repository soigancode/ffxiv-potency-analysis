"""Extract crit and direct-hit raid effects from official PvE job guides."""

import json
import os
import shutil
import tempfile
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ..patches import patch_order
from ..raid_effects import (
    EFFECT_JOBS,
    action_effects,
    description_effects,
    job_action_path,
    resolve_effects,
    validate_effect_manifest,
)
from ..reference_data import reference_path
from .fetch import fetch_job_guide
from .snapshot import JOBGUIDE_URL_TEMPLATE, LATEST_KNOWN_PATCH


def parse_raid_effects(html: str, job: str) -> list[dict[str, object]]:
    """Fail if a required action or rate changes to unsupported wording."""
    if job not in EFFECT_JOBS:
        raise ValueError(f"unsupported raid-buff job: {job!r}")
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for action in EFFECT_JOBS[job]:
        rows = [
            row
            for row in soup.select('tr[id^="pve_action__"]')
            if (name := row.select_one("td.skill strong")) is not None
            and name.get_text(" ", strip=True) == action
        ]
        if len(rows) != 1:
            raise ValueError(f"expected one PvE job-guide row for {action!r}, found {len(rows)}")
        content = rows[0].select_one("td.content")
        if content is None:
            raise ValueError(f"missing job-guide description for {action!r}")
        description = content.get_text(" ", strip=True)
        result.extend(description_effects(action, description, job))
    return result


def update_raid_effects(
    output_root: Path,
    patch: str = LATEST_KNOWN_PATCH,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    if patch != LATEST_KNOWN_PATCH:
        raise ValueError(
            f"only patch {LATEST_KNOWN_PATCH} is supported for now; received {patch!r}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / "raid_effects"
    with tempfile.TemporaryDirectory(prefix=".raid-effects-", dir=output_root) as temporary:
        staged = Path(temporary) / "staged"
        seed = destination if (destination / "datasets.json").is_file() else reference_path(
            "raid_effects", "datasets.json"
        ).parent
        shutil.copytree(seed, staged)
        manifest_path = staged / "datasets.json"
        manifest = json.loads(manifest_path.read_text())
        validate_effect_manifest(manifest, staged, data_root=output_root)
        rows = manifest["effect_sets"]
        latest = max(rows, key=lambda row: patch_order(row["valid_from"]))
        if patch_order(patch) < patch_order(latest["verified_through"]):
            raise ValueError("cannot update raid effects into an older verified patch")
        effects = []
        for job in EFFECT_JOBS:
            actions = job_action_path(output_root, job, patch)
            if actions is not None:
                for effect in action_effects(actions, job):
                    effect.pop("bonus")
                    effect["source"] = "job_actions"
                    effects.append(effect)
                continue
            source = staged / "sources" / patch / f"{job}.html"
            fetch_job_guide(JOBGUIDE_URL_TEMPLATE.format(job=job), source, transport=transport)
            effects.extend(parse_raid_effects(source.read_text(encoding="utf-8"), job))
        candidate = {"patch": patch, "effects": effects}
        resolve_effects(candidate, output_root, patch)
        previous = json.loads((staged / latest["file"]).read_text())
        # References are part of the schema: promoting an inline value to a job
        # reference is also a dataset change, even if today's percentages match.
        unchanged = previous["effects"] == effects
        if unchanged:
            latest["verified_through"] = patch
            filename = latest["file"]
        else:
            filename = f"{patch}.json"
            if latest["valid_from"] == patch:
                latest["verified_through"] = patch
            else:
                end = latest.get("valid_until")
                latest["valid_until"] = patch
                row = {"id": "effects_" + patch.replace(".", "_"), "file": filename,
                       "valid_from": patch, "verified_through": patch}
                if end is not None:
                    row["valid_until"] = end
                rows.append(row)
            (staged / filename).write_text(json.dumps(candidate, indent=2) + "\n")
        manifest["last_capture"] = {"patch": patch}
        validate_effect_manifest(manifest, staged, data_root=output_root)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        backup = Path(temporary) / "backup"
        if destination.exists():
            os.replace(destination, backup)
        try:
            os.replace(staged, destination)
        except OSError:
            if backup.exists():
                os.replace(backup, destination)
            raise
    return destination / filename
