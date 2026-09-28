import json
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.fflogs import ReportReference, download_report_events, refresh_report_rankings


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
                                        "encounterID": 1,
                                        "kill": True,
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
                            }
                        }
                    }
                },
            )
        if "Targetability" in query:
            assert variables["filter"] == 'type="targetabilityupdate"'
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
    assert json.loads(result.buff_events.read_text())[0]["type"] == "removebuff"
    assert json.loads(result.targetability_events.read_text())[0]["targetable"] == 0
    assert json.loads(result.encounter_overkill_events.read_text())[0]["sourceID"] == 9
    assert json.loads(result.fight.read_text())["name"] == "Test Boss"
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
        assert body["variables"] == {"code": "abc123", "fightIDs": [9]}
        return httpx.Response(
            200,
            json={
                "data": {
                    "reportData": {
                        "report": {
                            "ndpsRankings": {"data": [{"id": 18, "amount": 12345.6}]},
                            "rdpsRankings": {"data": [{"id": 18, "amount": 12222.2}]},
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
    }
    assert damage.read_text() == '[{"amount": 123}]'
