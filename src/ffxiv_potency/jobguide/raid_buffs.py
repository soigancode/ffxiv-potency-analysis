"""Extract crit and direct-hit raid effects from official PvE job guides."""

import json
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .fetch import fetch_job_guide
from .snapshot import LATEST_KNOWN_PATCH

EFFECT_JOBS = {
    "dragoon": ("Battle Litany",),
    "bard": ("Battle Voice", "Army's Paeon", "The Wanderer's Minuet"),
    "scholar": ("Chain Stratagem",),
}
GUIDE_URL = "https://eu.finalfantasyxiv.com/jobguide/{job}/"
RATE_PATTERN = re.compile(
    r"(?:(critical|direct) hit rate|rate at which target takes (critical) hits)[^.%]*? by (\d+)%",
    re.IGNORECASE,
)


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
        matches = list(RATE_PATTERN.finditer(description))
        if len(matches) != 1:
            raise ValueError(f"expected one crit/DH rate for {action!r}, found {len(matches)}")
        match = matches[0]
        kind = "critical" if "critical" in match.group(0).casefold() else "direct"
        target = "enemy" if action == "Chain Stratagem" else "player"
        result.append(
            {
                "action": action,
                "status": action,
                "job": job,
                "target": target,
                "rate": kind,
                "bonus": int(match.group(3)) / 100,
            }
        )
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
    destination = output_root / "raid_buffs" / patch
    effects = []
    for job in EFFECT_JOBS:
        url = GUIDE_URL.format(job=job)
        source = destination / f"{job}.html"
        fetch_job_guide(url, source, transport=transport)
        effects.extend(parse_raid_effects(source.read_text(encoding="utf-8"), job))
    output = destination / "effects.json"
    output.write_text(
        json.dumps({"patch": patch, "effects": effects}, indent=2) + "\n", encoding="utf-8"
    )
    return output
