"""Download selected FF Logs fight metadata and paginated events."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from .client import FFLogsClient, FFLogsError
from .reference import ReportReference, report_directory_name

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
        combatTime
        encounterID
        kill
        friendlyPlayers
      }
      rdpsRankings: rankings(fightIDs: $fightIDs, playerMetric: rdps)
      ndpsRankings: rankings(fightIDs: $fightIDs, playerMetric: ndps)
      dpsRankings: rankings(fightIDs: $fightIDs, playerMetric: dps)
      masterData {
        logVersion
        gameVersion
        lang
        actors { id gameID name type subType petOwner server }
        abilities { gameID name type }
      }
      combatants: events(fightIDs: $fightIDs, dataType: CombatantInfo, limit: 300) {
        data nextPageTimestamp
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
      dpsRankings: rankings(fightIDs: $fightIDs, playerMetric: dps)
    }
  }
}
"""

_REPORT_DATE_QUERY = """
query ReportDate($code: String!) {
  reportData { report(code: $code) { startTime } }
}
"""

_CHECKPOINT_FIGHTS_QUERY = """
query CheckpointFights($code: String!) {
  reportData {
    report(code: $code) {
      fights { id encounterID startTime endTime kill friendlyPlayers }
    }
  }
}
"""

_FIGHT_CONTEXT_QUERY = """
query FightContext($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      fights(fightIDs: $fightIDs) { id friendlyPlayers }
      combatants: events(fightIDs: $fightIDs, dataType: CombatantInfo, limit: 300) {
        data nextPageTimestamp
      }
    }
  }
}
"""

_COMBAT_TIME_QUERY = """
query CombatTime($code: String!, $fightIDs: [Int]) {
  reportData {
    report(code: $code) {
      fights(fightIDs: $fightIDs) { id startTime endTime combatTime }
    }
  }
}
"""

_EVENT_QUERY = """
query ReportEvents($code: String!, $fightIDs: [Int], $sourceID: Int, $targetID: Int, $startTime: Float, $includeResources: Boolean) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        sourceID: $sourceID
        targetID: $targetID
        dataType: DATA_TYPE
        startTime: $startTime
        includeResources: $includeResources
        limit: 10000
      ) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

_OVERKILL_QUERY = """
query EncounterOverkill($code: String!, $fightIDs: [Int], $startTime: Float, $filter: String!) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        startTime: $startTime
        filterExpression: $filter
        limit: 10000
      ) { data nextPageTimestamp }
    }
  }
}
"""

_TARGETABILITY_QUERY = """
query Targetability($code: String!, $fightIDs: [Int], $startTime: Float, $filter: String!) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        startTime: $startTime
        filterExpression: $filter
        limit: 10000
      ) { data nextPageTimestamp }
    }
  }
}
"""

_ACTOR_EVENTS_QUERY = """
query ActorStatusEvents($code: String!, $fightIDs: [Int], $startTime: Float, $filter: String!, $abilityID: Float) {
  reportData {
    report(code: $code) {
      events(fightIDs: $fightIDs, startTime: $startTime, abilityID: $abilityID,
             filterExpression: $filter, limit: 10000) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

_DEBUFF_TYPES = {"applydebuff", "refreshdebuff", "removedebuff",
                 "applydebuffstack", "removedebuffstack"}
_LIFE_TYPES = {"death", "resurrect"}
_TRANSCENDENT_BUFF_ID = 1000418


class _GraphQLClient(Protocol):
    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]: ...


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
    debuff_events: Path | None = None
    targetability_events: Path | None = None
    encounter_overkill_events: Path | None = None
    life_events: Path | None = None
    revival_buff_events: Path | None = None
    combatant_info_events: Path | None = None


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


def _saved_rankings(rdps: Any, ndps: Any, dps: Any = None) -> dict[str, Any]:
    """Label cached metrics so an older rDPS response is never shown as nDPS."""
    return {
        "metric": "ndps",
        "rankings": ndps if ndps is not None else {},
        "rdps": rdps if rdps is not None else {},
        **({"dps": dps} if dps is not None else {}),
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
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        report = _report_from(
            client.graphql(
                _RANKINGS_QUERY,
                {"code": reference.report_code, "fightIDs": [reference.fight_id]},
            )
        )
    return _write_json(
        directory / "rankings.json",
        _saved_rankings(report.get("rdpsRankings"), report.get("ndpsRankings"),
                        report.get("dpsRankings")),
    )


def refresh_report_date(
    reference: ReportReference, directory: Path, *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Add the report's absolute start time to an older cached fight."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        report = _report_from(client.graphql(
            _REPORT_DATE_QUERY, {"code": reference.report_code},
        ))
    started = report.get("startTime")
    if not isinstance(started, (int, float)):
        raise FFLogsError("report has no valid start time")
    path = directory / "fight.json"
    fight = json.loads(path.read_text(encoding="utf-8"))
    fight["reportStartTime"] = started
    return _write_json(path, fight)


def refresh_fight_context(
    reference: ReportReference, directory: Path, *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Recover fight participants and initial auras for an older saved download."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        report = _report_from(client.graphql(
            _FIGHT_CONTEXT_QUERY, {"code": reference.report_code, "fightIDs": [reference.fight_id]},
        ))
    fights = report.get("fights")
    fight = next((row for row in fights if isinstance(row, dict)
                  and row.get("id") == reference.fight_id), None) if isinstance(fights, list) else None
    if fight is None or not isinstance(fight.get("friendlyPlayers"), list):
        raise FFLogsError("fight participants were missing from FF Logs")
    combatants = report.get("combatants")
    if not isinstance(combatants, dict):
        raise FFLogsError("initial combatant auras were incomplete")
    events = combatants.get("data")
    if not isinstance(events, list) or combatants.get("nextPageTimestamp") is not None:
        raise FFLogsError("initial combatant auras were incomplete")
    path = directory / "fight.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["friendlyPlayers"] = fight["friendlyPlayers"]
    _write_json(path, saved)
    _write_json(directory / "combatant-info-events.json", events)


def refresh_combat_time(
    reference: ReportReference, directory: Path, *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Add recorded combat duration to an older download, retaining its start."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        report = _report_from(client.graphql(
            _COMBAT_TIME_QUERY, {"code": reference.report_code, "fightIDs": [reference.fight_id]},
        ))
    fights = report.get("fights")
    current = next((f for f in fights if isinstance(f, dict) and f.get("id") == reference.fight_id),
                   None) if isinstance(fights, list) else None
    path = directory / "fight.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (current is None or "combatTime" not in current
            or any(current.get(k) != saved.get(k) for k in ("startTime", "endTime"))):
        raise FFLogsError("combat-time metadata does not match the saved fight")
    return _write_json(path, {**saved, "combatTime": current["combatTime"]})


def refresh_targetability_events(
    reference: ReportReference,
    directory: Path,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Add encounter-wide targetability updates to an existing saved fight."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        events = _download_targetability_events(client, reference)
    return _write_json(directory / "targetability-events.json", events)


def _download_targetability_events(
    client: _GraphQLClient, reference: ReportReference
) -> list[dict[str, Any]]:
    """Fetch encounter-wide targetability updates, including boss and add events."""
    events: list[dict[str, Any]] = []
    start_time: float | None = None
    while True:
        report = _report_from(client.graphql(_TARGETABILITY_QUERY, {
            "code": reference.report_code,
            "fightIDs": [reference.fight_id],
            "startTime": start_time,
            "filter": 'type="targetabilityupdate" or type="death"',
        }))
        page = report.get("events")
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise FFLogsError("invalid targetability event response")
        events.extend(
            event for event in page["data"]
            if isinstance(event, dict) and event.get("type") in {"targetabilityupdate", "death"}
        )
        next_timestamp = page.get("nextPageTimestamp")
        if next_timestamp is None:
            return events
        if not isinstance(next_timestamp, (int, float)) or next_timestamp == start_time:
            raise FFLogsError("invalid targetability pagination timestamp")
        start_time = float(next_timestamp)


def _download_encounter_overkills(
    client: FFLogsClient, reference: ReportReference
) -> list[dict[str, Any]]:
    """Fetch killing hits from every player, including other party members."""
    events: list[dict[str, Any]] = []
    start_time: float | None = None
    while True:
        report = _report_from(client.graphql(_OVERKILL_QUERY, {
            "code": reference.report_code,
            "fightIDs": [reference.fight_id],
            "startTime": start_time,
            "filter": 'type="damage" and overkill > 0',
        }))
        page = report.get("events")
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise FFLogsError("invalid encounter overkill event response")
        events.extend(event for event in page["data"] if isinstance(event, dict)
                      and event.get("type") == "damage"
                      and isinstance(event.get("overkill"), (int, float))
                      and event["overkill"] > 0)
        next_timestamp = page.get("nextPageTimestamp")
        if next_timestamp is None:
            return events
        if not isinstance(next_timestamp, (int, float)) or next_timestamp == start_time:
            raise FFLogsError("invalid encounter overkill pagination timestamp")
        start_time = float(next_timestamp)


def _download_actor_events(
    client: _GraphQLClient, reference: ReportReference,
    kinds: set[str], filter_expression: str, *, ability_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch raw status changes; the Debuffs table is source-oriented in some reports."""
    events: list[dict[str, Any]] = []
    start_time: float | None = None
    while True:
        report = _report_from(client.graphql(_ACTOR_EVENTS_QUERY, {
            "code": reference.report_code,
            "fightIDs": [reference.fight_id],
            "startTime": start_time,
            "filter": filter_expression,
            "abilityID": float(ability_id) if ability_id is not None else None,
        }))
        page = report.get("events")
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise FFLogsError("invalid actor status event response")
        events.extend(
            event for event in page["data"]
            if isinstance(event, dict) and event.get("type") in kinds
            and event.get("targetID") == reference.source_id
            and (ability_id is None or event.get("abilityGameID") == ability_id)
        )
        next_timestamp = page.get("nextPageTimestamp")
        if next_timestamp is None:
            return events
        if not isinstance(next_timestamp, (int, float)) or next_timestamp == start_time:
            raise FFLogsError("invalid actor status pagination timestamp")
        start_time = float(next_timestamp)


def refresh_player_status_events(
    reference: ReportReference, directory: Path, *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Backfill raw debuff and life events for fights saved with the old query."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        debuffs = _download_actor_events(
            client, reference, _DEBUFF_TYPES,
            'type="applydebuff" or type="refreshdebuff" or type="removedebuff" '
            'or type="applydebuffstack" or type="removedebuffstack"',
        )
        life = _download_actor_events(
            client, reference, _LIFE_TYPES, 'type="death" or type="resurrect"',
        )
    _write_json(directory / "debuff-events.json", debuffs)
    _write_json(directory / "life-events.json", life)


def refresh_revival_buff_events(
    reference: ReportReference, directory: Path, *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Fetch incoming Transcendent applications, including healer LB3 revivals."""
    life_path = directory / "life-events.json"
    life = json.loads(life_path.read_text(encoding="utf-8")) if life_path.is_file() else []
    if not any(isinstance(event, dict) and event.get("type") == "death"
               and event.get("targetID") == reference.source_id for event in life):
        return _write_json(directory / "revival-buff-events.json", [])
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        events = _download_actor_events(
            client, reference, {"applybuff", "refreshbuff"},
            'type="applybuff" or type="refreshbuff"',
            ability_id=_TRANSCENDENT_BUFF_ID,
        )
    return _write_json(directory / "revival-buff-events.json", events)


def refresh_encounter_overkill_events(
    reference: ReportReference, directory: Path, *,
    client_id: str | None = None,
    client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Backfill killing hits for fights downloaded before this feature existed."""
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        events = _download_encounter_overkills(client, reference)
    return _write_json(directory / "encounter-overkill-events.json", events)


def _download_events(
    client: _GraphQLClient,
    reference: ReportReference,
    data_type: str,
    *,
    include_resources: bool = False,
    encounter_wide: bool = False,
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
                "sourceID": None if encounter_wide or data_type in {"Buffs", "Debuffs"} else reference.source_id,
                "targetID": reference.source_id if data_type in {"Buffs", "Debuffs"} else None,
                "startTime": start_time,
                "includeResources": include_resources,
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


def _download_encounter_damage(client: _GraphQLClient, reference: ReportReference,
                               master_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Save only each enemy instance's first party hit to establish appearances."""
    actors = {a["id"]: a for a in master_data.get("actors", [])}
    first: dict[tuple[Any, Any], dict[str, Any]] = {}
    for event in _download_events(client, reference, "DamageDone", encounter_wide=True):
        source = actors.get(event.get("sourceID"), {})
        target = actors.get(event.get("targetID"), {})
        if (event.get("type") != "damage" or event.get("amount", 0) <= 0
                or target.get("type") != "NPC" or target.get("petOwner") is not None
                or not (source.get("type") == "Player" or source.get("petOwner") is not None)):
            continue
        key = event.get("targetID"), event.get("targetInstance", 1)
        if key not in first or event["timestamp"] < first[key]["timestamp"]:
            first[key] = event
    return sorted(first.values(), key=lambda e: e["timestamp"])


def refresh_encounter_damage_events(reference: ReportReference, directory: Path) -> Path:
    master_data = json.loads((directory / "master-data.json").read_text(encoding="utf-8"))
    with FFLogsClient.from_environment() as client:
        events = _download_encounter_damage(client, reference, master_data)
        targetability = _download_targetability_events(client, reference)
    _write_json(directory / "targetability-events.json", targetability)
    return _write_json(directory / "encounter-damage-events.json", events)


def _checkpoint_context(client: _GraphQLClient, reference: ReportReference,
                        fight: dict[str, Any]) -> dict[str, Any]:
    """Fetch an exact carry only after a verified phase-one kill without a wipe."""
    report = _report_from(client.graphql(
        _CHECKPOINT_FIGHTS_QUERY, {"code": reference.report_code},
    ))
    fights = report.get("fights")
    if not isinstance(fights, list):
        raise FFLogsError("report fight timeline is missing for Lindwurm II")
    start = fight.get("startTime")
    if not isinstance(start, (int, float)):
        raise FFLogsError("Lindwurm II has no valid start time")
    earlier = [row for row in fights if isinstance(row, dict)
               and isinstance(row.get("startTime"), (int, float))
               and row["startTime"] < start]
    if not earlier:
        return {"carry": "unknown"}
    previous = max(earlier, key=lambda row: row["startTime"])
    if previous.get("encounterID") == 105 and previous.get("kill") is False:
        return {"carry": False}
    if (previous.get("encounterID") != 104 or previous.get("kill") is not True
            or not isinstance(previous.get("id"), int)
            or not isinstance(previous.get("endTime"), (int, float))
            or previous["endTime"] > start
            or reference.source_id not in (previous.get("friendlyPlayers") or [])):
        return {"carry": "unknown"}
    prior = ReportReference(reference.report_code, previous["id"], reference.source_id)
    casts = _download_events(client, prior, "Casts")
    damage = _download_events(client, prior, "DamageDone")
    if not casts or not damage:
        return {"carry": "unknown"}
    return {
        "carry": True,
        "reportCode": reference.report_code,
        "sourceID": reference.source_id,
        "fightID": reference.fight_id,
        "previousFight": previous,
        "casts": casts,
        "damage": damage,
    }


def refresh_checkpoint_context(
    reference: ReportReference, directory: Path, *,
    client_id: str | None = None, client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Fetch the phase-one pull for an existing Lindwurm II saved fight."""
    fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
    if fight.get("encounterID") != 105:
        raise ValueError("checkpoint context applies only to Lindwurm II")
    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        context = _checkpoint_context(client, reference, fight)
    return _write_json(directory / "checkpoint-context.json", context)


def download_report_events(
    reference: ReportReference,
    output_root: Path,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> DownloadResult:
    """Download metadata, casts, damage, and player buff/debuff state changes."""

    directory = (
        output_root
        / report_directory_name(reference.report_code)
        / f"fight-{reference.fight_id}"
        / f"source-{reference.source_id}"
    )

    with FFLogsClient.from_environment(client_id, client_secret, transport=transport) as client:
        metadata = client.graphql(
            _METADATA_QUERY,
            {"code": reference.report_code, "fightIDs": [reference.fight_id]},
        )
        report = _report_from(metadata)
        fights = report.get("fights")
        if not isinstance(fights, list) or len(fights) != 1:
            raise FFLogsError(f"fight {reference.fight_id} was not found")
        if not isinstance(fights[0].get("friendlyPlayers"), list):
            raise FFLogsError("fight participants were missing from FF Logs")
        master_data = report.get("masterData")
        if not isinstance(master_data, dict):
            raise FFLogsError("report master data was missing")
        rdps = report.get("rdpsRankings")
        ndps = report.get("ndpsRankings")
        checkpoint = (_checkpoint_context(client, reference, fights[0])
                      if fights[0].get("encounterID") == 105 else None)

        combatants = report.get("combatants")
        if not isinstance(combatants, dict):
            raise FFLogsError("initial combatant auras were incomplete")
        combatant_events = combatants.get("data")
        if not isinstance(combatant_events, list) or combatants.get("nextPageTimestamp") is not None:
            raise FFLogsError("initial combatant auras were incomplete")

        damage_events = _download_events(client, reference, "DamageDone")
        cast_events = _download_events(client, reference, "Casts")
        buff_events = _download_events(client, reference, "Buffs")
        # Debuffs as a data type can select effects *done by* the player. Raw
        # event types followed by an explicit target check capture incoming
        # Weakness, Brink of Death, and encounter debuffs as well.
        debuff_events = _download_actor_events(
            client, reference, _DEBUFF_TYPES,
            'type="applydebuff" or type="refreshdebuff" or type="removedebuff" '
            'or type="applydebuffstack" or type="removedebuffstack"',
        )
        life_events = _download_actor_events(
            client, reference, _LIFE_TYPES, 'type="death" or type="resurrect"',
        )
        revival_buff_events = (
            _download_actor_events(
                client, reference, {"applybuff", "refreshbuff"},
                'type="applybuff" or type="refreshbuff"',
                ability_id=_TRANSCENDENT_BUFF_ID,
            ) if any(event.get("type") == "death" for event in life_events) else []
        )
        targetability_events = _download_targetability_events(client, reference)
        encounter_overkills = _download_encounter_overkills(client, reference)
        encounter_damage = (_download_encounter_damage(client, reference, master_data)
                            if fights[0].get("encounterID") in {4549, 4550, 4551} else None)

    fight = {**fights[0], "reportStartTime": report.get("startTime")}
    if encounter_damage is not None:
        _write_json(directory / "encounter-damage-events.json", encounter_damage)
    fight_path = _write_json(directory / "fight.json", fight)
    master_path = _write_json(directory / "master-data.json", master_data)
    damage_path = _write_json(directory / "damage-events.json", damage_events)
    cast_path = _write_json(directory / "cast-events.json", cast_events)
    buff_path = _write_json(directory / "buff-events.json", buff_events)
    debuff_path = _write_json(directory / "debuff-events.json", debuff_events)
    life_path = _write_json(directory / "life-events.json", life_events)
    revival_buff_path = _write_json(directory / "revival-buff-events.json", revival_buff_events)
    targetability_path = _write_json(directory / "targetability-events.json", targetability_events)
    overkill_path = _write_json(directory / "encounter-overkill-events.json", encounter_overkills)
    combatant_path = _write_json(directory / "combatant-info-events.json", combatant_events)
    rankings_path = _write_json(directory / "rankings.json", _saved_rankings(rdps, ndps, report.get("dpsRankings")))
    if checkpoint is not None:
        _write_json(directory / "checkpoint-context.json", checkpoint)
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
        debuff_events=debuff_path,
        life_events=life_path,
        revival_buff_events=revival_buff_path,
        targetability_events=targetability_path,
        encounter_overkill_events=overkill_path,
        combatant_info_events=combatant_path,
    )
