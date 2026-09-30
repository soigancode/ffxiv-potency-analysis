"""Fetch lightweight fight and player choices for a report URL."""

from dataclasses import dataclass

import httpx

from .client import FFLogsClient, FFLogsError

_REPORT_CHOICES_QUERY = """
query ReportChoices($code: String!) {
  reportData {
    report(code: $code) {
      fights { id name encounterID startTime endTime kill friendlyPlayers }
      masterData { actors { id name type subType } }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class ReportPlayer:
    id: int
    name: str
    job: str


@dataclass(frozen=True, slots=True)
class ReportFight:
    id: int
    name: str
    encounter_id: int
    duration_seconds: float | None
    kill: bool | None
    players: tuple[ReportPlayer, ...]


def report_fights(
    code: str, *, client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[ReportFight, ...]:
    """List encounter fights and their actual player participants, in report order."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        data = client.graphql(_REPORT_CHOICES_QUERY, {"code": code})
    report_data = data.get("reportData")
    report = report_data.get("report") if isinstance(report_data, dict) else None
    if not isinstance(report, dict):
        raise FFLogsError(f"report {code} was not found")
    fights = report.get("fights")
    master_data = report.get("masterData")
    actors = master_data.get("actors") if isinstance(master_data, dict) else None
    if not isinstance(fights, list) or not isinstance(actors, list):
        raise FFLogsError("report fights or player data were missing from FF Logs")
    players = {
        actor["id"]: ReportPlayer(actor["id"], actor["name"], actor["subType"])
        for actor in actors
        if isinstance(actor, dict) and actor.get("type") == "Player"
        and isinstance(actor.get("id"), int) and not isinstance(actor["id"], bool)
        and isinstance(actor.get("name"), str)
        and isinstance(actor.get("subType"), str)
    }
    choices = []
    for fight in fights:
        if not isinstance(fight, dict):
            continue
        fight_id = fight.get("id")
        encounter_id = fight.get("encounterID")
        if (not isinstance(fight_id, int) or isinstance(fight_id, bool)
                or not isinstance(encounter_id, int) or isinstance(encounter_id, bool)
                or encounter_id <= 0
                or not isinstance(fight.get("name"), str)):
            continue
        participants = fight.get("friendlyPlayers")
        if not isinstance(participants, list):
            raise FFLogsError(f"fight {fight_id} has no player participants in FF Logs")
        start, end = fight.get("startTime"), fight.get("endTime")
        duration = ((end - start) / 1000 if isinstance(start, (int, float))
                    and isinstance(end, (int, float)) and end >= start else None)
        choices.append(ReportFight(
            fight_id, fight["name"], encounter_id, duration,
            fight.get("kill") if isinstance(fight.get("kill"), bool) else None,
            tuple(players[person] for person in participants if person in players),
        ))
    return tuple(choices)
