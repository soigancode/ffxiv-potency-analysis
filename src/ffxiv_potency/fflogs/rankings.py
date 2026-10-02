"""Resolve current encounter rankings to selected FF Logs report sources."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import count
from typing import Any

import httpx

from ..jobs import job_name
from .client import FFLogsClient, FFLogsError
from .partitions import current_partition
from .reference import ReportReference, valid_report_code

MAX_RANK_RANGE = 25

_RANKINGS_QUERY = """
query EncounterRankings($encounterID: Int!, $specName: String!, $partition: Int) {
  worldData {
    encounter(id: $encounterID) {
      id
      name
      characterRankings(specName: $specName, metric: rdps, partition: $partition, page: 1)
    }
  }
}
"""

_PAGED_RANKINGS_QUERY = _RANKINGS_QUERY.replace(
    "$specName: String!", "$specName: String!, $page: Int!"
).replace("page: 1)", "page: $page)")

# Endgame dungeons publish character Damage rankings, while their saved rDPS
# ranking records contain no character entries. Criterion and raids use rDPS.
_ENDGAME_DUNGEONS = frozenset({4549, 4551})


def _character_ranking_query(encounter_id: int, *, paged: bool) -> str:
    query = _PAGED_RANKINGS_QUERY if paged else _RANKINGS_QUERY
    if encounter_id in _ENDGAME_DUNGEONS:
        return query.replace("metric: rdps", "metric: dps")
    return query


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
    on_status: Callable[[str], None] | None = None,
) -> ReportReference:
    if on_status is not None:
        on_status(f"Identifying player for rank {position}...")
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
    partition: int | None = None,
) -> tuple[ReportReference, ...]:
    """Get the first ten ranking slots; fail if a slot has no accessible report."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        rows = _ranking_rows(client.graphql(
            _character_ranking_query(encounter_id, paged=False), {
                "encounterID": encounter_id, "specName": job_name(job),
                "partition": current_partition(encounter_id, partition),
            }
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
    partition: int | None = None,
    on_status: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> ReportReference:
    """Resolve any positive leaderboard position without loading other reports."""
    if rank < 1:
        raise ValueError("rank must be a positive number")
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        if on_progress is not None:
            on_progress(0, 1)
        position = 0
        for page in count(1):
            if on_status is not None:
                on_status(f"Loading leaderboard page {page}...")
            rows = _ranking_rows(client.graphql(_character_ranking_query(encounter_id, paged=True), {
                "encounterID": encounter_id, "specName": job_name(job), "page": page,
                "partition": current_partition(encounter_id, partition),
            }), encounter_id)
            if not rows:
                break
            if rank <= position + len(rows):
                reference = _resolve_row(client, rows[rank - position - 1], rank, encounter_id, job, {},
                                         on_status)
                if on_progress is not None:
                    on_progress(1, 1)
                return reference
            position += len(rows)
    raise FFLogsError(f"rank {rank} does not exist for {job} in encounter {encounter_id}")


def _resolve_rank_batch(
    client: FFLogsClient, rows: list[Any], first_position: int, encounter_id: int, job: str,
    cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]],
    on_progress: Callable[[int], None] | None = None,
) -> list[ReportReference | FFLogsError]:
    """Resolve independent reports concurrently, retaining rank order and shared fights."""
    groups: dict[tuple[str, int], list[tuple[int, Any]]] = {}
    for index, row in enumerate(rows):
        try:
            key = _ranking_report(row) if isinstance(row, dict) else ("", index)
        except FFLogsError:
            key = "", index
        groups.setdefault(key, []).append((index, row))
    results: dict[int, ReportReference | FFLogsError] = {}

    def resolve_group(group: list[tuple[int, Any]]) -> tuple[
        dict[int, ReportReference | FFLogsError],
        dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]],
    ]:
        local_cache = dict(cache)
        resolved: dict[int, ReportReference | FFLogsError] = {}
        for index, row in group:
            try:
                resolved[index] = _resolve_row(
                    client, row, first_position + index, encounter_id, job, local_cache,
                )
            except FFLogsError as exc:
                resolved[index] = exc
        return resolved, local_cache

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(resolve_group, group) for group in groups.values()]
        found = 0
        for future in as_completed(futures):
            resolved, updated_cache = future.result()
            results.update(resolved)
            cache.update(updated_cache)
            found += sum(isinstance(item, ReportReference) for item in resolved.values())
            if on_progress is not None:
                on_progress(found)
    return [results[index] for index in range(len(rows))]


def accessible_ranked_sources(
    encounter_id: int, job: str, *, client_id: str | None = None,
    client_secret: str | None = None, transport: httpx.BaseTransport | None = None,
    partition: int | None = None,
    on_status: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    limit: int = 10,
) -> tuple[tuple[tuple[int, ReportReference], ...], tuple[tuple[int, str], ...]]:
    """Collect the requested accessible rankings, preserving skipped positions."""
    if type(limit) is not int or not 1 <= limit <= MAX_RANK_RANGE:
        raise ValueError(f"ranking limit must be between 1 and {MAX_RANK_RANGE}")
    found: list[tuple[int, ReportReference]] = []
    skipped: list[tuple[int, str]] = []
    cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]] = {}
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        if on_progress is not None:
            on_progress(0, limit)
        position = 0
        for page in range(1, 6):
            if on_status is not None:
                on_status(f"Loading leaderboard page {page}...")
            rows = _ranking_rows(client.graphql(_character_ranking_query(encounter_id, paged=True), {
                "encounterID": encounter_id, "specName": job_name(job), "page": page,
                "partition": current_partition(encounter_id, partition),
            }), encounter_id)
            if not rows:
                break
            offset = 0
            while offset < len(rows):
                batch = rows[offset:offset + limit - len(found)]
                if on_status is not None:
                    on_status(f"Identifying players for ranks {position + 1}-{position + len(batch)}...")
                callback = (lambda count: on_progress(len(found) + count, limit)) if on_progress is not None else None
                resolved = _resolve_rank_batch(client, batch, position + 1, encounter_id, job, cache, callback)
                for reference in resolved:
                    position += 1
                    if isinstance(reference, FFLogsError):
                        reason = str(reference)
                        if not any(marker in reason for marker in (
                            "no usable report", "no player name", "anonymous actor names",
                        )):
                            raise reference
                        skipped.append((position, reason))
                        continue
                    found.append((position, reference))
                offset += len(batch)
                if len(found) == limit:
                    return tuple(found), tuple(skipped)
    if not found:
        raise FFLogsError("none of the ranked logs have accessible report references")
    if on_progress is not None:
        on_progress(len(found), len(found))
    return tuple(found), tuple(skipped)


def validate_rank_range(first: int, last: int) -> None:
    """Require an inclusive range of two to 25 leaderboard positions."""
    if first < 1 or last <= first:
        raise ValueError("rank range must have two increasing positive positions")
    if last - first + 1 > MAX_RANK_RANGE:
        raise ValueError(f"rank range can contain at most {MAX_RANK_RANGE} positions")


def validate_rank_positions(positions: tuple[int, ...]) -> None:
    """Require two to 25 distinct positive leaderboard positions."""
    if (not 2 <= len(positions) <= MAX_RANK_RANGE
            or any(position < 1 for position in positions)
            or len(set(positions)) != len(positions)):
        raise ValueError(
            f"rank selection requires 2 to {MAX_RANK_RANGE} distinct positive positions"
        )


def ranked_sources_at_positions(
    encounter_id: int, job: str, positions: tuple[int, ...], *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None, partition: int | None = None,
    on_status: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[tuple[tuple[int, ReportReference], ...], tuple[tuple[int, str], ...]]:
    """Resolve selected ranks in input order, fetching only their ranking pages."""
    validate_rank_positions(positions)
    found: list[tuple[int, ReportReference]] = []
    skipped: list[tuple[int, str]] = []
    cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]] = {}
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        if on_progress is not None:
            on_progress(0, len(positions))
        variables = {
            "encounterID": encounter_id, "specName": job_name(job),
            "partition": current_partition(encounter_id, partition),
        }
        if on_status is not None:
            on_status("Loading leaderboard page 1...")
        first = _ranking_rows(client.graphql(
            _character_ranking_query(encounter_id, paged=True), {**variables, "page": 1},
        ), encounter_id)
        if not first:
            raise FFLogsError(f"no ranked {job} logs exist for encounter {encounter_id}")
        page_size = len(first)
        pages = {1: first}
        for done, position in enumerate(positions, 1):
            page, index = divmod(position - 1, page_size)
            page += 1
            if page not in pages:
                if on_status is not None:
                    on_status(f"Loading leaderboard page {page}...")
                pages[page] = _ranking_rows(client.graphql(
                    _character_ranking_query(encounter_id, paged=True),
                    {**variables, "page": page},
                ), encounter_id)
            rows = pages[page]
            if index >= len(rows):
                raise FFLogsError(
                    f"rank {position} does not exist for {job} in encounter {encounter_id}"
                )
            try:
                found.append((position, _resolve_row(
                    client, rows[index], position, encounter_id, job, cache, on_status,
                )))
            except FFLogsError as exc:
                skipped.append((position, str(exc)))
            if on_progress is not None:
                on_progress(done, len(positions))
    if not found:
        raise FFLogsError(f"no accessible {job} logs at the selected ranks")
    return tuple(found), tuple(skipped)


def ranked_sources_in_range(
    encounter_id: int, job: str, first: int, last: int, *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None, partition: int | None = None,
    on_status: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[tuple[tuple[int, ReportReference], ...], tuple[tuple[int, str], ...]]:
    """Resolve every leaderboard position in an inclusive range across pages."""
    validate_rank_range(first, last)
    found: list[tuple[int, ReportReference]] = []
    skipped: list[tuple[int, str]] = []
    cache: dict[tuple[str, int], tuple[list[dict[str, Any]], set[int]]] = {}
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        if on_progress is not None:
            on_progress(0, last - first + 1)
        if on_status is not None:
            on_status("Loading leaderboard page 1...")
        first_rows = _ranking_rows(client.graphql(_character_ranking_query(encounter_id, paged=True), {
            "encounterID": encounter_id, "specName": job_name(job), "page": 1,
            "partition": current_partition(encounter_id, partition),
        }), encounter_id)
        if not first_rows:
            raise FFLogsError(f"rank {last} does not exist for {job} in encounter {encounter_id}")
        page_size = len(first_rows)
        first_page = (first - 1) // page_size + 1
        position = (first_page - 1) * page_size
        for page in count(first_page):
            if on_status is not None:
                on_status(f"Loading leaderboard page {page}...")
            rows = first_rows if page == 1 else _ranking_rows(client.graphql(_character_ranking_query(encounter_id, paged=True), {
                "encounterID": encounter_id, "specName": job_name(job), "page": page,
                "partition": current_partition(encounter_id, partition),
            }), encounter_id)
            if not rows:
                break
            for row in rows:
                position += 1
                if position < first:
                    continue
                if position > last:
                    break
                try:
                    found.append((position, _resolve_row(
                        client, row, position, encounter_id, job, cache, on_status,
                    )))
                except FFLogsError as exc:
                    skipped.append((position, str(exc)))
                if on_progress is not None:
                    on_progress(position - first + 1, last - first + 1)
            if position >= last:
                break
    if position < last:
        raise FFLogsError(f"rank {last} does not exist for {job} in encounter {encounter_id}")
    if not found:
        raise FFLogsError(f"no accessible {job} logs at ranks {first}-{last}")
    return tuple(found), tuple(skipped)
