"""Minimal saved-player fixtures shared by CLI command tests."""

import json
from pathlib import Path


def _write_selected_log(directory: Path, source_id: int, subtype: str = "Machinist") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "master-data.json").write_text(
        json.dumps(
            {
                "actors": [{"id": source_id, "type": "Player", "subType": subtype}],
            }
        ),
        encoding="utf-8",
    )
    fight_id = (int(directory.parent.name.removeprefix("fight-"))
                if directory.parent.name.startswith("fight-") else 1)
    (directory / "fight.json").write_text(json.dumps({
        "id": fight_id, "startTime": 0, "reportStartTime": 1777593600000,
    }), encoding="utf-8")
    for name in ("damage-events.json", "cast-events.json"):
        (directory / name).write_text("{}", encoding="utf-8")
    (directory / "rankings.json").write_text(
        '{"metric":"ndps","rankings":{},"rdps":{}}', encoding="utf-8"
    )

