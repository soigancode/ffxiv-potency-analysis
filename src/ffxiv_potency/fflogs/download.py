"""Download selected FF Logs fight metadata and paginated events."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .client import FFLogsClient, FFLogsError
from .reference import ReportReference

_METADATA_QUERY = """
query ReportMetadata($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      code
      title
      startTime
      endTime
      fights(fightIDs: $fightIDs) {
        id
        name
        startTime
        endTime
        encounterID
        kill
      }
      rdpsRankings: rankings(fightIDs: $fightIDs, playerMetric: rdps)
      ndpsRankings: rankings(fightIDs: $fightIDs, playerMetric: ndps)
      masterData {
        logVersion
        gameVersion
        lang
        actors { id gameID name type subType petOwner server }
        abilities { gameID name type }
      }
    }
  }
}
"""

_RANKINGS_QUERY = """
query ReportRankings($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      rdpsRankings: rankings(fightIDs: $fightIDs, playerMetric: rdps)
      ndpsRankings: rankings(fightIDs: $fightIDs, playerMetric: ndps)
    }
  }
}
"""

_EVENT_QUERY = """
query ReportEvents($code: String!, $fightIDs: [Int], $sourceID: Int, $targetID: Int, $startTime: Float) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        sourceID: $sourceID
        targetID: $targetID
        dataType: DATA_TYPE
        startTime: $startTime
        limit: 10000
      ) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class DownloadResult:
    directory: Path
    fight: Path
    master_data: Path
    damage_events: Path
    cast_events: Path
    rankings: Path
    damage_event_count: int
    cast_event_count: int
    buff_events: Path | None = None


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _report_from(data: dict[str, Any]) -> dict[str, Any]:
    report_data = data.get("reportData")
    report = report_data.get("report") if isinstance(report_data, dict) else None
    if not isinstance(report, dict):
        raise FFLogsError("report was not found or is not publicly accessible")
    return report


def _saved_rankings(rdps: Any, ndps: Any) -> dict[str, Any]:
    """Label cached metrics so an older rDPS response is never shown as nDPS."""
    return {
        "metric": "ndps",
        "rankings": ndps if ndps is not None else {},
        "rdps": rdps if rdps is not None else {},
    }


def refresh_report_rankings(
    reference: ReportReference,
    directory: Path,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Update rDPS and nDPS for a saved fight without downloading its events."""
    resolved_id = client_id or os.environ.get("FFLOGS_CLIENT_ID", "")
    resolved_secret = client_secret or os.environ.get("FFLOGS_CLIENT_SECRET", "")
    with FFLogsClient(resolved_id, resolved_secret, transport=transport) as client:
        report = _report_from(
            client.graphql(
                _RANKINGS_QUERY,
                {"code": reference.report_code, "fightIDs": [reference.fight_id]},
            )
        )
    return _write_json(
        directory / "rankings.json",
        _saved_rankings(report.get("rdpsRankings"), report.get("ndpsRankings")),
    )


def _download_events(
    client: FFLogsClient,
    reference: ReportReference,
    data_type: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    start_time: float | None = None
    while True:
        query = _EVENT_QUERY.replace("DATA_TYPE", data_type)
        data = client.graphql(
            query,
            {
                "code": reference.report_code,
                "fightIDs": [reference.fight_id],
                "sourceID": None if data_type == "Buffs" else reference.source_id,
                "targetID": reference.source_id if data_type == "Buffs" else None,
                "startTime": start_time,
            },
        )
        report = _report_from(data)
        page = report.get("events")
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise FFLogsError(f"invalid {data_type} event response")
        events.extend(event for event in page["data"] if isinstance(event, dict))
        next_timestamp = page.get("nextPageTimestamp")
        if next_timestamp is None:
            return events
        if not isinstance(next_timestamp, (int, float)) or next_timestamp == start_time:
            raise FFLogsError(f"invalid {data_type} pagination timestamp")
        start_time = float(next_timestamp)


def download_report_events(
    reference: ReportReference,
    output_root: Path,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> DownloadResult:
    """Download metadata, casts, damage, and buff state changes."""

    resolved_id = client_id or os.environ.get("FFLOGS_CLIENT_ID", "")
    resolved_secret = client_secret or os.environ.get("FFLOGS_CLIENT_SECRET", "")
    directory = (
        output_root
        / reference.report_code
        / f"fight-{reference.fight_id}"
        / f"source-{reference.source_id}"
    )

    with FFLogsClient(resolved_id, resolved_secret, transport=transport) as client:
        metadata = client.graphql(
            _METADATA_QUERY,
            {"code": reference.report_code, "fightIDs": [reference.fight_id]},
        )
        report = _report_from(metadata)
        fights = report.get("fights")
        if not isinstance(fights, list) or len(fights) != 1:
            raise FFLogsError(f"fight {reference.fight_id} was not found")
        master_data = report.get("masterData")
        if not isinstance(master_data, dict):
            raise FFLogsError("report master data was missing")
        rdps = report.get("rdpsRankings")
        ndps = report.get("ndpsRankings")

        damage_events = _download_events(client, reference, "DamageDone")
        cast_events = _download_events(client, reference, "Casts")
        buff_events = _download_events(client, reference, "Buffs")

    fight_path = _write_json(directory / "fight.json", fights[0])
    master_path = _write_json(directory / "master-data.json", master_data)
    damage_path = _write_json(directory / "damage-events.json", damage_events)
    cast_path = _write_json(directory / "cast-events.json", cast_events)
    buff_path = _write_json(directory / "buff-events.json", buff_events)
    rankings_path = _write_json(directory / "rankings.json", _saved_rankings(rdps, ndps))
    return DownloadResult(
        directory=directory,
        fight=fight_path,
        master_data=master_path,
        damage_events=damage_path,
        cast_events=cast_path,
        rankings=rankings_path,
        damage_event_count=len(damage_events),
        cast_event_count=len(cast_events),
        buff_events=buff_path,
    )
