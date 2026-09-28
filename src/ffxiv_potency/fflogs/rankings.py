"""Resolve current encounter rankings to selected FF Logs report sources."""

from itertools import count
from typing import Any

import httpx

from .client import FFLogsClient, FFLogsError
from .reference import ReportReference, valid_report_code

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

_PAGED_RANKINGS_QUERY = _RANKINGS_QUERY.replace(
    "$specName: String!", "$specName: String!, $page: Int!"
).replace("page: 1)", "page: $page)")

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
        or not valid_report_code(code)
        or not isinstance(fight_id, int)
        or fight_id <= 0
    ):
        raise FFLogsError("a ranked log has no usable report code or fight ID")
    return code, fight_id


def _ranking_rows(data: dict[str, Any], encounter_id: int) -> list[Any]:
    world = data.get("worldData")
    encounter = world.get("encounter") if isinstance(world, dict) else None
    if not isinstance(encounter, dict) or encounter.get("id") != encounter_id:
        raise FFLogsError(f"encounter {encounter_id} was not found")
    result = encounter.get("characterRankings")
    rows = result.get("rankings") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise FFLogsError("FF Logs did not return encounter character rankings")
    return rows


def _resolve_row(
    client: FFLogsClient, row: Any, position: int, encounter_id: int, job: str,
    cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]],
) -> ReportReference:
    if not isinstance(row, dict) or not isinstance(row.get("name"), str):
        raise FFLogsError(f"rank {position} has no player name")
    code, fight_id = _ranking_report(row)
    key = code, fight_id
    if key not in cache:
        details = client.graphql(_REPORT_SOURCES_QUERY, {"code": code, "fightIDs": [fight_id]})
        report_data = details.get("reportData")
        report = report_data.get("report") if isinstance(report_data, dict) else None
        fights = report.get("fights") if isinstance(report, dict) else None
        master = report.get("masterData") if isinstance(report, dict) else None
        actors = master.get("actors") if isinstance(master, dict) else None
        if (
            not isinstance(fights, list) or len(fights) != 1
            or fights[0].get("id") != fight_id
            or fights[0].get("encounterID") != encounter_id
            or not isinstance(fights[0].get("friendlyPlayers"), list)
            or not isinstance(actors, list)
        ):
            raise FFLogsError(f"rank {position} has no matching fight metadata")
        cache[key] = (
            [actor for actor in actors if isinstance(actor, dict)],
            {id_ for id_ in fights[0]["friendlyPlayers"] if isinstance(id_, int)},
        )
    actors, fight_players = cache[key]
    job_players = [
        actor for actor in actors
        if actor.get("type") == "Player"
        and isinstance(actor.get("subType"), str)
        and actor["subType"].casefold() == job.casefold()
        and isinstance(actor.get("id"), int)
        and actor["id"] in fight_players
    ]
    if row["name"].casefold() == "anonymous" and len(job_players) > 1:
        raise FFLogsError(f"rank {position} uses anonymous actor names; source is ambiguous")
    candidates = [
        actor for actor in job_players
        if isinstance(actor.get("name"), str)
        and actor["name"].casefold() == row["name"].casefold()
    ]
    if not candidates and len(job_players) == 1:
        sole = job_players[0]
        actor_name = sole.get("name")
        if (row["name"].casefold() == "anonymous" or (
            isinstance(actor_name, str) and actor_name.casefold() == "anonymous"
        ) or actor_name == f"Player ({sole['id']})"):
            # Anonymous reports still give their sole job player a report-local actor ID.
            return ReportReference(code, fight_id, sole["id"])
    if len(candidates) != 1:
        if job_players and all(
            isinstance(actor.get("name"), str)
            and actor["name"].casefold() == "anonymous"
            for actor in job_players
        ):
            raise FFLogsError(f"rank {position} uses anonymous actor names; source is ambiguous")
        available = (
            ", ".join(f"{actor.get('name', '?')} (source {actor['id']})" for actor in job_players)
            or "none"
        )
        same_name = [
            actor for actor in actors
            if isinstance(actor.get("name"), str)
            and actor["name"].casefold() == row["name"].casefold()
        ]
        matching = (
            ", ".join(
                f"source {actor.get('id', '?')}, type {actor.get('type', '?')}, "
                f"job {actor.get('subType', '?')}"
                for actor in same_name
            ) or "none"
        )
        raise FFLogsError(
            f"could not identify the {job} player {row['name']!r} at rank "
            f"{position} in report {code}, fight {fight_id}; "
            f"fight players: {sorted(fight_players)}; "
            f"matching name in report: {matching}; "
            f"{job} players in report: {available}"
        )
    return ReportReference(code, fight_id, candidates[0]["id"])


def top_ranked_sources(
    encounter_id: int, job: str, *, client_id: str | None = None,
    client_secret: str | None = None, transport: httpx.BaseTransport | None = None,
) -> tuple[ReportReference, ...]:
    """Get the first ten ranking slots; fail if a slot has no accessible report."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        rows = _ranking_rows(client.graphql(
            _RANKINGS_QUERY, {"encounterID": encounter_id, "specName": job.capitalize()}
        ), encounter_id)
        if len(rows) < 2:
            raise FFLogsError(f"fewer than two ranked {job} logs exist for encounter {encounter_id}")
        cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]] = {}
        return tuple(
            _resolve_row(client, row, rank, encounter_id, job, cache)
            for rank, row in enumerate(rows[:10], 1)
        )


def ranked_source(
    encounter_id: int, job: str, rank: int, *, client_id: str | None = None,
    client_secret: str | None = None, transport: httpx.BaseTransport | None = None,
) -> ReportReference:
    """Resolve any positive leaderboard position without loading other reports."""
    if rank < 1:
        raise ValueError("rank must be a positive number")
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        position = 0
        for page in count(1):
            rows = _ranking_rows(client.graphql(_PAGED_RANKINGS_QUERY, {
                "encounterID": encounter_id, "specName": job.capitalize(), "page": page,
            }), encounter_id)
            if not rows:
                break
            if rank <= position + len(rows):
                return _resolve_row(client, rows[rank - position - 1], rank, encounter_id, job, {})
            position += len(rows)
    raise FFLogsError(f"rank {rank} does not exist for {job} in encounter {encounter_id}")


def accessible_ranked_sources(
    encounter_id: int, job: str, *, client_id: str | None = None,
    client_secret: str | None = None, transport: httpx.BaseTransport | None = None,
) -> tuple[tuple[tuple[int, ReportReference], ...], tuple[tuple[int, str], ...]]:
    """Collect ten accessible rankings, preserving skipped leaderboard positions."""
    found: list[tuple[int, ReportReference]] = []
    skipped: list[tuple[int, str]] = []
    cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]] = {}
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        position = 0
        for page in range(1, 6):
            rows = _ranking_rows(client.graphql(_PAGED_RANKINGS_QUERY, {
                "encounterID": encounter_id, "specName": job.capitalize(), "page": page,
            }), encounter_id)
            if not rows:
                break
            for row in rows:
                position += 1
                try:
                    reference = _resolve_row(client, row, position, encounter_id, job, cache)
                except FFLogsError as exc:
                    reason = str(exc)
                    if not any(marker in reason for marker in (
                        "no usable report", "no player name", "anonymous actor names",
                    )):
                        raise
                    skipped.append((position, reason))
                    continue
                found.append((position, reference))
                if len(found) == 10:
                    return tuple(found), tuple(skipped)
    if not found:
        raise FFLogsError("none of the ranked logs have accessible report references")
    return tuple(found), tuple(skipped)
