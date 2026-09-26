"""Resolve current encounter rankings to selected FF Logs report sources."""

import os
from typing import Any

import httpx

from .client import FFLogsClient, FFLogsError
from .reference import ReportReference

_RANKINGS_QUERY = """
query EncounterRankings($encounterID: Int!, $specName: String!) {
  worldData {
    encounter(id: $encounterID) {
      id
      name
      characterRankings(specName: $specName, metric: rdps, page: 1)
    }
  }
}
"""

_REPORT_SOURCES_QUERY = """
query RankingReportSources($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      fights(fightIDs: $fightIDs) { id encounterID friendlyPlayers }
      masterData { actors { id name type subType } }
    }
  }
}
"""


def _ranking_report(row: dict[str, Any]) -> tuple[str, int]:
    report = row.get("report")
    code = report.get("code") if isinstance(report, dict) else report
    fight_id = report.get("fightID") if isinstance(report, dict) else None
    if fight_id is None:
        fight_id = row.get("fightID")
    if (
        not isinstance(code, str)
        or not code.isalnum()
        or not isinstance(fight_id, int)
        or fight_id <= 0
    ):
        raise FFLogsError("a ranked log has no usable report code or fight ID")
    return code, fight_id


def top_ranked_sources(
    encounter_id: int,
    job: str,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[ReportReference, ...]:
    """Get the latest partition's ten highest rDPS logs for an encounter and job."""
    with FFLogsClient(
        client_id or os.environ.get("FFLOGS_CLIENT_ID", ""),
        client_secret or os.environ.get("FFLOGS_CLIENT_SECRET", ""),
        transport=transport,
    ) as client:
        data = client.graphql(
            _RANKINGS_QUERY, {"encounterID": encounter_id, "specName": job.capitalize()}
        )
        world = data.get("worldData")
        encounter = world.get("encounter") if isinstance(world, dict) else None
        if not isinstance(encounter, dict) or encounter.get("id") != encounter_id:
            raise FFLogsError(f"encounter {encounter_id} was not found")
        result = encounter.get("characterRankings")
        rows = result.get("rankings") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise FFLogsError("FF Logs did not return encounter character rankings")
        if len(rows) < 2:
            raise FFLogsError(
                f"fewer than two ranked {job} logs exist for encounter {encounter_id}"
            )

        references: list[ReportReference] = []
        report_cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]] = {}
        for position, row in enumerate(rows[:10], 1):
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                raise FFLogsError(f"rank {position} has no player name")
            code, fight_id = _ranking_report(row)
            key = code, fight_id
            if key not in report_cache:
                details = client.graphql(
                    _REPORT_SOURCES_QUERY, {"code": code, "fightIDs": [fight_id]}
                )
                report_data = details.get("reportData")
                report = report_data.get("report") if isinstance(report_data, dict) else None
                fights = report.get("fights") if isinstance(report, dict) else None
                master = report.get("masterData") if isinstance(report, dict) else None
                actors = master.get("actors") if isinstance(master, dict) else None
                if (
                    not isinstance(fights, list)
                    or len(fights) != 1
                    or fights[0].get("id") != fight_id
                    or fights[0].get("encounterID") != encounter_id
                    or not isinstance(fights[0].get("friendlyPlayers"), list)
                    or not isinstance(actors, list)
                ):
                    raise FFLogsError(f"rank {position} has no matching fight metadata")
                report_cache[key] = (
                    [actor for actor in actors if isinstance(actor, dict)],
                    {id_ for id_ in fights[0]["friendlyPlayers"] if isinstance(id_, int)},
                )
            actors, fight_players = report_cache[key]
            job_players = [
                actor
                for actor in actors
                if actor.get("type") == "Player"
                and isinstance(actor.get("subType"), str)
                and actor["subType"].casefold() == job.casefold()
                and isinstance(actor.get("id"), int)
                and actor["id"] in fight_players
            ]
            candidates = [
                actor
                for actor in job_players
                if isinstance(actor.get("name"), str)
                and actor["name"].casefold() == row["name"].casefold()
            ]
            if len(candidates) != 1:
                available = (
                    ", ".join(
                        f"{actor.get('name', '?')} (source {actor['id']})" for actor in job_players
                    )
                    or "none"
                )
                same_name = [
                    actor
                    for actor in actors
                    if isinstance(actor.get("name"), str)
                    and actor["name"].casefold() == row["name"].casefold()
                ]
                matching = (
                    ", ".join(
                        f"source {actor.get('id', '?')}, type {actor.get('type', '?')}, "
                        f"job {actor.get('subType', '?')}"
                        for actor in same_name
                    )
                    or "none"
                )
                raise FFLogsError(
                    f"could not identify the {job} player {row['name']!r} at rank "
                    f"{position} in report {code}, fight {fight_id}; "
                    f"fight players: {sorted(fight_players)}; "
                    f"matching name in report: {matching}; "
                    f"{job} players in report: {available}"
                )
            references.append(ReportReference(code, fight_id, candidates[0]["id"]))
        return tuple(references)
