"""A leaderboard entry must point to the exact player in its report fight."""

import json

import httpx
import pytest

from ffxiv_potency.fflogs import FFLogsError, ReportReference, top_ranked_sources


def test_current_job_rankings_resolve_report_source_ids_in_order() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        requests.append(body)
        if "EncounterRankings" in body["query"]:
            assert "metric: rdps" in body["query"]
            assert "partition:" not in body["query"]  # FF Logs defaults to the latest.
            assert body["variables"] == {"encounterID": 101, "specName": "Machinist"}
            return httpx.Response(
                200,
                json={
                    "data": {
                        "worldData": {
                            "encounter": {
                                "id": 101,
                                "name": "Vamp Fatale",
                                "characterRankings": {
                                    "rankings": [
                                        {
                                            "name": "First",
                                            "report": {"code": "abc123", "fightID": 9},
                                        },
                                        {
                                            "name": "Second",
                                            "report": {"code": "def456", "fightID": 4},
                                        },
                                    ]
                                },
                            }
                        }
                    }
                },
            )
        assert "RankingReportSources" in body["query"]
        code = body["variables"]["code"]
        fight_id = body["variables"]["fightIDs"][0]
        name = "First" if code == "abc123" else "Second"
        actor_id = 18 if code == "abc123" else 7
        return httpx.Response(
            200,
            json={
                "data": {
                    "reportData": {
                        "report": {
                            "fights": [
                                {"id": fight_id, "encounterID": 101, "friendlyPlayers": [actor_id]}
                            ],
                            "masterData": {
                                "actors": [
                                    {
                                        "id": actor_id,
                                        "name": name,
                                        "type": "Player",
                                        "subType": "Machinist",
                                    },
                                    {"id": 99, "name": name, "type": "Pet", "subType": "Machinist"},
                                ]
                            },
                        }
                    }
                }
            },
        )

    sources = top_ranked_sources(
        101,
        "machinist",
        client_id="client",
        client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert sources == (ReportReference("abc123", 9, 18), ReportReference("def456", 4, 7))
    assert len(requests) == 3


def test_rejects_ranking_without_report_fight() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={
                "data": {
                    "worldData": {
                        "encounter": {
                            "id": 101,
                            "characterRankings": {
                                "rankings": [
                                    {"name": "First", "report": {"code": "abc123"}},
                                    {"name": "Second", "report": {"code": "def456"}},
                                ]
                            },
                        }
                    }
                }
            },
        )

    with pytest.raises(FFLogsError, match="no usable report code or fight ID"):
        top_ranked_sources(
            101,
            "machinist",
            client_id="client",
            client_secret="secret",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.parametrize("extra_machinist", [False, True])
def test_ranking_name_mismatch_does_not_guess_player(extra_machinist: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "worldData": {
                            "encounter": {
                                "id": 101,
                                "characterRankings": {
                                    "rankings": [
                                        {
                                            "name": "Current Name",
                                            "report": {"code": "abc123", "fightID": 2},
                                        },
                                        {
                                            "name": "Other",
                                            "report": {"code": "def456", "fightID": 3},
                                        },
                                    ]
                                },
                            }
                        }
                    }
                },
            )
        code = body["variables"]["code"]
        actors = [
            {"id": 18, "name": "Old Name", "type": "Player", "subType": "Machinist"},
            {"id": 19, "name": "Sun Atakai", "type": "Player", "subType": "Dragoon"},
        ]
        if extra_machinist:
            actors.append({"id": 20, "name": "Third", "type": "Player", "subType": "Machinist"})
        if code == "def456":
            actors = [{"id": 7, "name": "Other", "type": "Player", "subType": "Machinist"}]
        return httpx.Response(
            200,
            json={
                "data": {
                    "reportData": {
                        "report": {
                            "fights": [
                                {
                                    "id": 2 if code == "abc123" else 3,
                                    "encounterID": 101,
                                    "friendlyPlayers": [18, 19, 20] if code == "abc123" else [7],
                                }
                            ],
                            "masterData": {"actors": actors},
                        }
                    }
                }
            },
        )

    kwargs = {
        "client_id": "client",
        "client_secret": "secret",
        "transport": httpx.MockTransport(handler),
    }
    with pytest.raises(
        FFLogsError,
        match=r"Current Name.*rank 1.*matching name in report: none;.*Old Name \(source 18\)",
    ):
        top_ranked_sources(101, "machinist", **kwargs)


def test_matching_name_with_unexpected_job_reports_actor_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "worldData": {
                            "encounter": {
                                "id": 101,
                                "characterRankings": {
                                    "rankings": [
                                        {
                                            "name": "Esser Kaatapoh",
                                            "report": {"code": "abc123", "fightID": 2},
                                        },
                                        {
                                            "name": "Other",
                                            "report": {"code": "def456", "fightID": 3},
                                        },
                                    ]
                                },
                            }
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "reportData": {
                        "report": {
                            "fights": [{"id": 2, "encounterID": 101, "friendlyPlayers": [18]}],
                            "masterData": {
                                "actors": [
                                    {
                                        "id": 18,
                                        "name": "Esser Kaatapoh",
                                        "type": "Player",
                                        "subType": None,
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        )

    with pytest.raises(
        FFLogsError,
        match=r"Esser Kaatapoh.*matching name in report: source 18, type Player, job None; "
        r"machinist players in report: none",
    ):
        top_ranked_sources(
            101,
            "machinist",
            client_id="client",
            client_secret="secret",
            transport=httpx.MockTransport(handler),
        )


def test_duplicate_report_actors_resolve_using_fight_participants() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "worldData": {
                            "encounter": {
                                "id": 101,
                                "characterRankings": {
                                    "rankings": [
                                        {
                                            "name": "Esser Kaatapoh",
                                            "amount": 19876.54,
                                            "report": {"code": "abc123", "fightID": 2},
                                        },
                                        {
                                            "name": "Other",
                                            "report": {"code": "def456", "fightID": 3},
                                        },
                                    ]
                                },
                            }
                        }
                    }
                },
            )
        code = body["variables"]["code"]
        assert "friendlyPlayers" in body["query"]
        actors = (
            [
                {"id": id_, "name": "Esser Kaatapoh", "type": "Player", "subType": subtype}
                for id_, subtype in [
                    (1, "Unknown"),
                    (2, "Machinist"),
                    (54, "Machinist"),
                    (56, "Machinist"),
                ]
            ]
            if code == "abc123"
            else [{"id": 7, "name": "Other", "type": "Player", "subType": "Machinist"}]
        )
        return httpx.Response(
            200,
            json={
                "data": {
                    "reportData": {
                        "report": {
                            "fights": [
                                {
                                    "id": 2 if code == "abc123" else 3,
                                    "encounterID": 101,
                                    "friendlyPlayers": [2, 57] if code == "abc123" else [7],
                                }
                            ],
                            "masterData": {"actors": actors},
                        }
                    }
                }
            },
        )

    assert top_ranked_sources(
        101,
        "machinist",
        client_id="client",
        client_secret="secret",
        transport=httpx.MockTransport(handler),
    ) == (ReportReference("abc123", 2, 2), ReportReference("def456", 3, 7))
