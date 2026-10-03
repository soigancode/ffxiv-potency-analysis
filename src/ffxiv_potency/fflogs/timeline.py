"""Capture fight-start evidence without changing saved analysis inputs."""

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

from .client import FFLogsClient, FFLogsError
from .reference import ReportReference, report_code_from_directory

_QUERY = r"""
query Timeline($code: String!, $fightIDs: [Int], $startTime: Float) {
  reportData {
    report(code: $code) {
      fights(fightIDs: $fightIDs) {
        id name encounterID startTime endTime combatTime
        dungeonPulls { startTime endTime }
      }
      events(fightIDs: $fightIDs, dataType: All, startTime: $startTime,
        filterExpression: "type=\"encounterstart\" or type=\"encounterend\" or type=\"dungeonstart\" or type=\"dungeonend\" or type=\"dungeonencounterstart\" or type=\"dungeonencounterend\"",
        limit: 10000) {
        data nextPageTimestamp
      }
    }
  }
}
"""


class _Client(Protocol):
    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]: ...


def capture_timeline(client: _Client, reference: ReportReference) -> dict[str, Any]:
    """Fetch unfiltered-by-player boundary events and metadata across all pages."""
    events = []
    fight = None
    cursor = None
    seen = set()
    while True:
        data = client.graphql(_QUERY, {
            "code": reference.report_code, "fightIDs": [reference.fight_id],
            "startTime": cursor,
        })
        report = data.get("reportData", {}).get("report")
        if not isinstance(report, dict):
            raise FFLogsError("timeline response is missing report data")
        fights = report.get("fights")
        if not isinstance(fights, list):
            raise FFLogsError("timeline response is missing fight metadata")
        current = next((f for f in fights if isinstance(f, dict)
                        and f.get("id") == reference.fight_id), None)
        if current is None:
            raise FFLogsError("timeline response is missing the selected fight")
        if fight is None:
            fight = current
        page = report.get("events")
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise FFLogsError("invalid timeline event response")
        events.extend(e for e in page["data"] if isinstance(e, dict))
        cursor = page.get("nextPageTimestamp")
        if cursor is None:
            return {"reportCode": reference.report_code, "fight": fight, "events": events}
        if not isinstance(cursor, (int, float)) or isinstance(cursor, bool) or cursor in seen:
            raise FFLogsError("invalid timeline pagination timestamp")
        seen.add(cursor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path, help="saved source directories")
    args = parser.parse_args()
    load_dotenv()
    try:
        selections = []
        for directory in args.directories:
            fight = json.loads((directory / "fight.json").read_text())
            code = report_code_from_directory(directory.parent.parent.name)
            if code is None or not isinstance(fight.get("id"), int):
                raise ValueError(f"cannot identify saved fight: {directory}")
            source = int(directory.name.removeprefix("source-"))
            selections.append((directory, ReportReference(code, fight["id"], source), fight))
        with FFLogsClient.from_environment() as client:
            for directory, reference, saved in selections:
                context = capture_timeline(client, reference)
                context["savedStartTime"] = saved.get("startTime")
                path = directory / "timeline-context.json"
                path.write_text(json.dumps(context, indent=2) + "\n")
                print(f"Saved {path}")
                print(json.dumps(context, indent=2))
    except (FFLogsError, httpx.HTTPError, OSError, ValueError) as error:
        parser.exit(1, f"Timeline research failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
