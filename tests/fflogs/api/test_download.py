import json
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.fflogs import ReportReference, download_report_events, refresh_report_rankings
from ffxiv_potency.fflogs.download import (
    _checkpoint_context,
    refresh_fight_context,
    refresh_report_date,
    refresh_revival_buff_events,
)


def test_mch_checkpoint_context_only_uses_immediately_preceding_phase_one_kill() -> None:
    fight = {"id": 23, "encounterID": 105, "startTime": 10000}
    previous = {"id": 22, "encounterID": 104, "kill": True,
                "startTime": 1000, "endTime": 9000, "friendlyPlayers": [2]}

    class Client:
        def __init__(self, fights):
            self.fights = fights
            self.events = []

        def graphql(self, query, variables):
            if "CheckpointFights" in query:
                assert variables == {"code": "abc123"}
                return {"reportData": {"report": {"fights": self.fights}}}
            self.events.append((query, variables))
            return {"reportData": {"report": {"events": {
                "data": [{"type": "cast" if "dataType: Casts" in query else "damage"}],
                "nextPageTimestamp": None,
            }}}}

    reference = ReportReference("abc123", 23, 2)
    client = Client([previous, fight])
    result = _checkpoint_context(client, reference, fight)
    assert result["carry"] is True
    assert result["previousFight"] == previous
    assert len(client.events) == 2
    assert all(variables["fightIDs"] == [22] and variables["sourceID"] == 2
               for _, variables in client.events)

    wiped = Client([previous, {"id": 23, "encounterID": 105, "kill": False,
                               "startTime": 9500, "endTime": 9700},
                    {"id": 24, "encounterID": 105, "startTime": 10000}])
    assert _checkpoint_context(wiped, reference, {**fight, "id": 24}) == {"carry": False}
    assert wiped.events == []
    partial = Client([fight])
    assert _checkpoint_context(partial, reference, fight) == {"carry": "unknown"}
    assert partial.events == []


def test_refresh_fight_context_preserves_saved_fight_and_initial_auras(tmp_path: Path) -> None:
    saved = tmp_path / "fight.json"
    saved.write_text('{"id":9,"encounterID":103,"startTime":100}', encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "test-token"})
        body = json.loads(request.content)
        assert "FightContext" in body["query"]
        assert "friendlyPlayers" in body["query"]
        assert "dataType: CombatantInfo" in body["query"]
        assert body["variables"] == {"code": "abc123", "fightIDs": [9]}
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 9, "friendlyPlayers": [18, 21, 22, 23]}],
            "combatants": {"data": [{"sourceID": 18, "auras": [{"ability": 1000042}]}],
                           "nextPageTimestamp": None},
        }}}})

    refresh_fight_context(
        ReportReference("abc123", 9, 18), tmp_path,
        client_id="test", client_secret="secret", transport=httpx.MockTransport(handler),
    )

    assert json.loads(saved.read_text()) == {
        "id": 9, "encounterID": 103, "startTime": 100,
        "friendlyPlayers": [18, 21, 22, 23],
    }
    assert json.loads((tmp_path / "combatant-info-events.json").read_text()) == [
        {"sourceID": 18, "auras": [{"ability": 1000042}]},
    ]


@pytest.mark.parametrize("report_code, directory_name", [
    ("abc123", "abc123"), ("a:DNaXrgHGZ8PbCkfL", "a-DNaXrgHGZ8PbCkfL"),
])
def test_downloads_metadata_and_paginated_events(
    tmp_path: Path, report_code: str, directory_name: str
) -> None:
    damage_pages = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal damage_pages
        if request.url.path == "/oauth/token":
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "test-token"})

        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        query = body["query"]
        variables = body["variables"]
        if "ReportMetadata" in query:
            assert "rdpsRankings: rankings(fightIDs: $fightIDs, playerMetric: rdps)" in query
            assert "ndpsRankings: rankings(fightIDs: $fightIDs, playerMetric: ndps)" in query
            return httpx.Response(
                200,
                json={
                    "data": {
                        "reportData": {
                            "report": {
                                "code": "abc123",
                                "title": "Test Report",
                                "startTime": 1000,
                                "endTime": 9000,
                                "fights": [
                                    {
                                        "id": 9,
                                        "name": "Test Boss",
                                        "startTime": 100,
                                        "endTime": 8000,
                                        "combatTime": 7800,
                                        "encounterID": 1,
                                        "kill": True,
                                        "friendlyPlayers": [18, 21],
                                    }
                                ],
                                "ndpsRankings": {
                                    "data": [
                                        {
                                            "roles": {
                                                "dps": {
                                                    "characters": [
                                                        {
                                                            "id": 18,
                                                            "name": "Test",
                                                            "amount": 12345.6,
                                                        }
                                                    ]
                                                }
                                            }
                                        }
                                    ]
                                },
                                "rdpsRankings": {
                                    "data": [
                                        {
                                            "roles": {
                                                "dps": {
                                                    "characters": [
                                                        {
                                                            "id": 18,
                                                            "name": "Test",
                                                            "amount": 12222.2,
                                                        }
                                                    ]
                                                }
                                            }
                                        }
                                    ]
                                },
                                    "masterData": {
                                    "logVersion": 1,
                                    "gameVersion": 1,
                                    "lang": "en",
                                    "actors": [],
                                        "abilities": [],
                                    },
                                    "combatants": {
                                        "data": [{"sourceID": 18, "auras": [
                                            {"ability": 1000042, "stacks": 1},
                                        ]}],
                                        "nextPageTimestamp": None,
                                    },
                            }
                        }
                    }
                },
            )
        if "Targetability" in query:
            assert variables["filter"] == 'type="targetabilityupdate" or type="death"'
            assert "sourceID" not in query
            return httpx.Response(200, json={"data": {"reportData": {"report": {
                "fights": [{"startTime": 100}],
                "masterData": {"actors": [{"id": 5, "name": "Test Boss"}]},
                "events": {"data": [{"type": "targetabilityupdate", "timestamp": 500,
                                    "sourceID": 5, "targetable": 0}],
                           "nextPageTimestamp": None},
            }}}})
        if "EncounterOverkill" in query:
            assert variables["filter"] == 'type="damage" and overkill > 0'
            assert "sourceID" not in query
            return httpx.Response(200, json={"data": {"reportData": {"report": {
                "events": {"data": [{"type": "damage", "timestamp": 700,
                                    "sourceID": 9, "targetID": 5, "overkill": 42}],
                           "nextPageTimestamp": None},
            }}}})
        if "ActorStatusEvents" in query:
            assert "dataType:" not in query
            assert "targetID:" not in query
            if variables["abilityID"] == 1000418.0:
                assert variables["filter"] == 'type="applybuff" or type="refreshbuff"'
                events = [
                    {"timestamp": 650, "type": "applybuff", "targetID": 18,
                     "sourceID": -1, "abilityGameID": 1000418},
                    {"timestamp": 651, "type": "applybuff", "targetID": 17,
                     "sourceID": -1, "abilityGameID": 1000418},
                ]
            elif 'type="applydebuff"' in variables["filter"]:
                events = [
                    {"timestamp": 300, "type": "applydebuff", "targetID": 18,
                     "abilityGameID": 43},
                    {"timestamp": 301, "type": "applydebuff", "targetID": 17,
                     "abilityGameID": 43},
                ]
            else:
                events = [
                    {"timestamp": 600, "type": "death", "targetID": 18},
                    {"timestamp": 601, "type": "death", "targetID": 17},
                    {"timestamp": 900, "type": "resurrect", "targetID": 18},
                ]
            return httpx.Response(200, json={"data": {"reportData": {"report": {
                "events": {"data": events, "nextPageTimestamp": None},
            }}}})
        if "DamageDone" in query:
            damage_pages += 1
            if damage_pages == 1:
                assert variables["startTime"] is None
                events = {"data": [{"timestamp": 100, "amount": 876}], "nextPageTimestamp": 500}
            else:
                assert variables["startTime"] == 500.0
                events = {"data": [{"timestamp": 500, "amount": 900}], "nextPageTimestamp": None}
        elif "Buffs" in query:
            assert variables["sourceID"] is None
            assert variables["targetID"] == 18
            events = {
                "data": [{"timestamp": 200, "type": "removebuff", "abilityGameID": 49}],
                "nextPageTimestamp": None,
            }
        else:
            assert "Casts" in query
            assert variables["sourceID"] == 18
            assert variables["targetID"] is None
            events = {"data": [{"timestamp": 50, "type": "cast"}], "nextPageTimestamp": None}
        return httpx.Response(
            200,
            json={"data": {"reportData": {"report": {"events": events}}}},
        )

    result = download_report_events(
        ReportReference(report_code=report_code, fight_id=9, source_id=18),
        tmp_path,
        client_id="client-id",
        client_secret="client-secret",
        transport=httpx.MockTransport(handler),
    )

    assert result.directory == tmp_path / directory_name / "fight-9" / "source-18"
    assert result.damage_event_count == 2
    assert result.cast_event_count == 1
    assert json.loads(result.damage_events.read_text()) == [
        {"timestamp": 100, "amount": 876},
        {"timestamp": 500, "amount": 900},
    ]
    assert json.loads(result.cast_events.read_text()) == [{"timestamp": 50, "type": "cast"}]
    assert result.buff_events is not None
    assert result.debuff_events is not None
    assert result.targetability_events is not None
    assert result.encounter_overkill_events is not None
    assert result.life_events is not None
    assert result.revival_buff_events is not None
    assert json.loads(result.buff_events.read_text())[0]["type"] == "removebuff"
    assert json.loads(result.debuff_events.read_text())[0]["type"] == "applydebuff"
    assert len(json.loads(result.debuff_events.read_text())) == 1
    assert [event["type"] for event in json.loads(result.life_events.read_text())] == [
        "death", "resurrect",
    ]
    assert [event["targetID"] for event in json.loads(
        result.revival_buff_events.read_text())] == [18]
    assert json.loads(result.targetability_events.read_text())[0]["targetable"] == 0
    assert json.loads(result.encounter_overkill_events.read_text())[0]["sourceID"] == 9
    assert json.loads(result.fight.read_text())["name"] == "Test Boss"
    assert json.loads(result.fight.read_text())["reportStartTime"] == 1000
    assert json.loads(result.fight.read_text())["friendlyPlayers"] == [18, 21]
    assert json.loads(result.fight.read_text())["combatTime"] == 7800
    assert result.combatant_info_events is not None
    assert json.loads(result.combatant_info_events.read_text())[0]["auras"][0]["ability"] == 1000042
    assert json.loads(result.master_data.read_text())["lang"] == "en"
    assert json.loads(result.rankings.read_text())["metric"] == "ndps"
    assert (
        json.loads(result.rankings.read_text())["rdps"]["data"][0]["roles"]["dps"]["characters"][0][
            "amount"
        ]
        == 12222.2
    )
    assert (
        json.loads(result.rankings.read_text())["rankings"]["data"][0]["roles"]["dps"][
            "characters"
        ][0]["amount"]
        == 12345.6
    )


def test_backfills_report_date_without_redownloading_events(tmp_path: Path) -> None:
    directory = tmp_path / "report/fight-3/source-4"
    directory.mkdir(parents=True)
    (directory / "fight.json").write_text('{"id":3,"startTime":500}')

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        assert "ReportDate" in body["query"]
        assert body["variables"] == {"code": "report"}
        return httpx.Response(200, json={"data": {"reportData": {
            "report": {"startTime": 1777593600000},
        }}})

    path = refresh_report_date(
        ReportReference("report", 3, 4), directory, client_id="id", client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert json.loads(path.read_text()) == {
        "id": 3, "startTime": 500, "reportStartTime": 1777593600000,
    }


def test_backfills_environment_sourced_transcendent_for_saved_death(tmp_path: Path) -> None:
    directory = tmp_path / "report/fight-2/source-18"
    directory.mkdir(parents=True)
    (directory / "life-events.json").write_text(
        '[{"type": "death", "targetID": 18, "timestamp": 1000}]', encoding="utf-8"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "test-token"})
        variables = json.loads(request.content)["variables"]
        assert variables["abilityID"] == 1000418.0
        assert variables["filter"] == 'type="applybuff" or type="refreshbuff"'
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "events": {"data": [
                {"type": "applybuff", "abilityGameID": 1000418,
                 "sourceID": -1, "targetID": 18, "timestamp": 1046},
                {"type": "applybuff", "abilityGameID": 1000418,
                 "sourceID": -1, "targetID": 17, "timestamp": 1046},
            ], "nextPageTimestamp": None},
        }}}})

    result = refresh_revival_buff_events(
        ReportReference("report", 2, 18), directory,
        client_id="id", client_secret="secret", transport=httpx.MockTransport(handler),
    )
    assert json.loads(result.read_text()) == [{
        "type": "applybuff", "abilityGameID": 1000418,
        "sourceID": -1, "targetID": 18, "timestamp": 1046,
    }]


def test_refreshes_old_rankings_without_redownloading_events(tmp_path: Path) -> None:
    directory = tmp_path / "abc123/fight-9/source-18"
    directory.mkdir(parents=True)
    damage = directory / "damage-events.json"
    damage.write_text('[{"amount": 123}]', encoding="utf-8")
    (directory / "rankings.json").write_text('{"old_rdps": 999}', encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "test-token"})
        body = json.loads(request.content)
        assert "ReportRankings" in body["query"]
        assert "playerMetric: ndps" in body["query"]
        assert "playerMetric: rdps" in body["query"]
        assert "playerMetric: dps" in body["query"]
        assert body["variables"] == {"code": "abc123", "fightIDs": [9]}
        return httpx.Response(
            200,
            json={
                "data": {
                    "reportData": {
                        "report": {
                            "ndpsRankings": {"data": [{"id": 18, "amount": 12345.6}]},
                            "rdpsRankings": {"data": [{"id": 18, "amount": 12222.2}]},
                            "dpsRankings": {"data": [{"id": 18, "amount": 13500.0}]},
                        }
                    }
                }
            },
        )

    path = refresh_report_rankings(
        ReportReference("abc123", 9, 18),
        directory,
        client_id="client-id",
        client_secret="client-secret",
        transport=httpx.MockTransport(handler),
    )
    assert path == directory / "rankings.json"
    assert json.loads(path.read_text()) == {
        "metric": "ndps",
        "rankings": {"data": [{"id": 18, "amount": 12345.6}]},
        "rdps": {"data": [{"id": 18, "amount": 12222.2}]},
        "dps": {"data": [{"id": 18, "amount": 13500.0}]},
    }
    assert damage.read_text() == '[{"amount": 123}]'
