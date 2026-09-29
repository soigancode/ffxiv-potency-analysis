"""Extract crit and direct-hit raid effects from official PvE job guides."""

import json
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .fetch import fetch_job_guide
from .snapshot import JOBGUIDE_URL_TEMPLATE, LATEST_KNOWN_PATCH

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
        target = "enemy" if action == "Chain Stratagem" else "player"
        for kind, bonus in parsed:
            result.append(
                {
                    "action": action,
                    "status": action,
                    "job": job,
                    "target": target,
                    "rate": kind,
                    "bonus": bonus,
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
    source_directory = output_root / "raid_effects" / "sources" / patch
    effects = []
    for job in EFFECT_JOBS:
        url = JOBGUIDE_URL_TEMPLATE.format(job=job)
        source = source_directory / f"{job}.html"
        fetch_job_guide(url, source, transport=transport)
        effects.extend(parse_raid_effects(source.read_text(encoding="utf-8"), job))
    output = output_root / "raid_effects" / f"{patch}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"patch": patch, "effects": effects}, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(output)
    return output
