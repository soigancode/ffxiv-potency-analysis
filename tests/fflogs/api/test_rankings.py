"""A leaderboard entry must point to the exact player in its report fight."""

import json

import httpx
import pytest

from ffxiv_potency.fflogs import FFLogsError, ReportReference, top_ranked_sources
from ffxiv_potency.fflogs.rankings import (
    accessible_ranked_sources,
    ranked_source,
    ranked_sources_at_positions,
    ranked_sources_in_range,
    validate_rank_range,
)


def test_rank_range_crosses_pages_without_resolving_earlier_reports() -> None:
    pages: list[int] = []
    reports: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            page = body["variables"]["page"]
            pages.append(page)
            rows = [
                {"name": f"Player {rank}", "report": {
                    "code": f"report{rank}", "fightID": 9,
                }}
                for rank in range((page - 1) * 100 + 1, page * 100 + 1)
            ]
            if page == 51:
                rows[0]["report"] = None  # rank 5001 is inaccessible
            return httpx.Response(200, json={"data": {"worldData": {"encounter": {
                "id": 103, "characterRankings": {"rankings": rows},
            }}}})
        code = body["variables"]["code"]
        reports.append(code)
        rank = int(code.removeprefix("report"))
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 9, "encounterID": 103, "friendlyPlayers": [2]}],
            "masterData": {"actors": [{
                "id": 2, "name": f"Player {rank}", "type": "Player",
                "subType": "Machinist",
            }]},
        }}}})

    selected, skipped = ranked_sources_in_range(
        103, "machinist", 5000, 5024, client_id="id", client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert pages == [1, 50, 51]
    assert reports == ["report5000", *(f"report{rank}" for rank in range(5002, 5025))]
    assert selected[0] == (5000, ReportReference("report5000", 9, 2))
    assert selected[-1] == (5024, ReportReference("report5024", 9, 2))
    assert len(selected) == 24
    assert [rank for rank, _ in skipped] == [5001]


def test_rank_range_requires_increasing_positions() -> None:
    validate_rank_range(20, 21)
    validate_rank_range(20, 44)
    with pytest.raises(ValueError, match="increasing positive"):
        ranked_sources_in_range(103, "machinist", 5000, 5000)
    with pytest.raises(ValueError, match="at most 25"):
        ranked_sources_in_range(103, "machinist", 5000, 5025)


def test_selected_positions_fetch_only_needed_pages_in_requested_order() -> None:
    pages: list[int] = []
    reports: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            page = body["variables"]["page"]
            pages.append(page)
            rows = [{"name": f"Player {rank}", "report": {
                "code": f"report{rank}", "fightID": 9,
            }} for rank in range((page - 1) * 100 + 1, page * 100 + 1)]
            if page == 2:
                rows[52]["report"] = None
            return httpx.Response(200, json={"data": {"worldData": {"encounter": {
                "id": 103, "characterRankings": {"rankings": rows},
            }}}})
        code = body["variables"]["code"]
        reports.append(code)
        rank = int(code.removeprefix("report"))
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 9, "encounterID": 103, "friendlyPlayers": [2]}],
            "masterData": {"actors": [{"id": 2, "name": f"Player {rank}",
                                      "type": "Player", "subType": "Machinist"}]},
        }}}})

    found, skipped = ranked_sources_at_positions(
        103, "machinist", (153, 1, 2), client_id="id", client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert pages == [1, 2]
    assert reports == ["report1", "report2"]
    assert [rank for rank, _ in found] == [1, 2]
    assert skipped[0][0] == 153


@pytest.mark.parametrize("positions", [(1,), (1, 1), (0, 2), tuple(range(1, 27))])
def test_selected_positions_require_distinct_positive_ranks(positions: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="2 to 25 distinct positive"):
        ranked_sources_at_positions(103, "machinist", positions)


@pytest.mark.parametrize("partition", [None, 2])
def test_one_rank_resolves_only_its_report(partition: int | None) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        requests.append(body)
        if "EncounterRankings" in body["query"]:
            return httpx.Response(200, json={"data": {"worldData": {"encounter": {
                "id": 1085, "characterRankings": {"rankings": [
                    {"name": "First", "report": {"code": "abc123", "fightID": 1}},
                    {"name": "Third", "report": {"code": "def456", "fightID": 2}},
                ]},
            }}}})
        assert body["variables"] == {"code": "def456", "fightIDs": [2]}
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 2, "encounterID": 1085, "friendlyPlayers": [7]}],
            "masterData": {"actors": [
                {"id": 7, "name": "Third", "type": "Player", "subType": "Bard"},
            ]},
        }}}})

    assert ranked_source(1085, "bard", 2, partition=partition,
                         client_id="id", client_secret="secret",
                         transport=httpx.MockTransport(handler)) == ReportReference("def456", 2, 7)
    assert requests[0]["variables"]["partition"] == (partition if partition is not None else 1)
    assert len(requests) == 2


@pytest.mark.parametrize("encounter,metric", [(4549, "dps"), (4550, "rdps"), (4551, "dps")])
def test_dungeon_rank_uses_supported_character_metric_without_partition(
    encounter: int, metric: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            assert body["variables"]["partition"] is None
            assert "$partition: Int)" in body["query"]
            assert f"metric: {metric}" in body["query"]
            return httpx.Response(200, json={"data": {"worldData": {"encounter": {
                "id": encounter, "characterRankings": {"rankings": [{
                    "name": "First", "report": {"code": "abc123", "fightID": 2},
                }]},
            }}}})
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 2, "encounterID": encounter, "friendlyPlayers": [7]}],
            "masterData": {"actors": [
                {"id": 7, "name": "First", "type": "Player", "subType": "Bard"},
            ]},
        }}}})

    assert ranked_source(encounter, "bard", 1, client_id="id", client_secret="secret",
                         transport=httpx.MockTransport(handler)) == ReportReference("abc123", 2, 7)


@pytest.mark.parametrize("encounter,partition", [
    (101, 13), (1083, 1), (1083, 8), (1084, 7), (1084, 8),
])
def test_rank_uses_selected_global_partition(encounter: int, partition: int) -> None:
    partitions: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            partitions.append(body["variables"]["partition"])
            return httpx.Response(200, json={"data": {"worldData": {"encounter": {
                "id": encounter, "characterRankings": {"rankings": [
                    {"name": "Yenn Ryder", "report": {
                        "code": "CcvRV1j2mYyD8FkG", "fightID": 4,
                    }},
                ]},
            }}}})
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 4, "encounterID": encounter, "friendlyPlayers": [287]}],
            "masterData": {"actors": [{
                "id": 287, "name": "Yenn Ryder", "type": "Player",
                "subType": "Machinist",
            }]},
        }}}})

    result = ranked_source(
        encounter, "machinist", 1, partition=partition,
        client_id="id", client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert result == ReportReference("CcvRV1j2mYyD8FkG", 4, 287)
    assert partitions == [partition]


def test_one_rank_requires_positive_position() -> None:
    with pytest.raises(ValueError, match="positive number"):
        ranked_source(1085, "bard", 0)


def test_one_rank_reads_later_pages_and_reports_missing_rank() -> None:
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            page = body["variables"]["page"]
            requested_pages.append(page)
            rows = (
                [{"name": f"Player {rank}"} for rank in range(1, 11)] if page == 1
                else [{"name": "Player 11", "report": {"code": "page2", "fightID": 5}}]
                if page == 2 else []
            )
            return httpx.Response(200, json={"data": {"worldData": {"encounter": {
                "id": 101, "characterRankings": {"rankings": rows},
            }}}})
        assert body["variables"] == {"code": "page2", "fightIDs": [5]}
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 5, "encounterID": 101, "friendlyPlayers": [7]}],
            "masterData": {"actors": [
                {"id": 7, "name": "Player 11", "type": "Player", "subType": "Bard"},
            ]},
        }}}})

    kwargs = {"client_id": "id", "client_secret": "secret", "transport": httpx.MockTransport(handler)}
    assert ranked_source(101, "bard", 11, **kwargs) == ReportReference("page2", 5, 7)
    assert requested_pages == [1, 2]
    requested_pages.clear()
    with pytest.raises(FFLogsError, match="rank 12 does not exist"):
        ranked_source(101, "bard", 12, **kwargs)
    assert requested_pages == [1, 2, 3]


def test_current_job_rankings_resolve_report_source_ids_in_order() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        requests.append(body)
        if "EncounterRankings" in body["query"]:
            assert "metric: rdps" in body["query"]
            assert "partition: $partition" in body["query"]
            assert body["variables"] == {
                "encounterID": 101, "specName": "Machinist", "partition": 7,
            }
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


def test_research_skips_unavailable_and_anonymous_rankings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            assert body["variables"]["page"] == 1
            rows = [
                {"name": f"Person {rank}", "report": (
                    None if rank == 3 else {"code": f"code{rank}", "fightID": 4}
                )}
                for rank in range(1, 13)
            ]
            data = {"worldData": {"encounter": {
                "id": 1085, "characterRankings": {"rankings": rows},
            }}}
        else:
            assert "RankingReportSources" in body["query"]
            rank = int(body["variables"]["code"].removeprefix("code"))
            data = {"reportData": {"report": {
                "fights": [{"id": 4, "encounterID": 1085,
                            "friendlyPlayers": [10, 11] if rank == 4 else [10]}],
                "masterData": {"actors": ([
                    {"id": id_, "name": "Anonymous", "type": "Player", "subType": "Bard"}
                    for id_ in (10, 11)
                ] if rank == 4 else [{
                    "id": 10, "name": f"Person {rank}", "type": "Player", "subType": "Bard",
                }])},
            }}}
        return httpx.Response(200, json={"data": data})

    ranked, skipped = accessible_ranked_sources(
        1085, "bard", client_id="id", client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert [rank for rank, _ in ranked] == [1, 2, 5, 6, 7, 8, 9, 10, 11, 12]
    assert [rank for rank, _ in skipped] == [3, 4]
    assert "no usable report" in skipped[0][1]
    assert "anonymous actor" in skipped[1][1]


@pytest.mark.parametrize(
    "rank_name, actor_name",
    [("Anonymous", "Player (7)"), ("Named on leaderboard", "Anonymous")],
)
def test_anonymous_report_code_resolves_sole_brd_in_fight(
    rank_name: str, actor_name: str
) -> None:
    anonymous_code = "a:DNaXrgHGZ8PbCkfL"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            rows = [] if body["variables"].get("page", 1) > 1 else [
                {"name": rank_name, "report": {
                    "code": anonymous_code, "fightID": 22,
                }},
                {"name": "Other", "report": {"code": "normal", "fightID": 1}},
            ]
            response = {"worldData": {"encounter": {
                "id": 102, "characterRankings": {"rankings": rows},
            }}}
        else:
            code = body["variables"]["code"]
            response = {"reportData": {"report": {
                "fights": [{"id": 22 if code == anonymous_code else 1,
                            "encounterID": 102, "friendlyPlayers": [7, 8]}],
                "masterData": {"actors": [
                    {"id": 7, "name": actor_name if code == anonymous_code else "Other",
                     "type": "Player", "subType": "Bard"},
                    {"id": 8, "name": "Anonymous", "type": "Player", "subType": "Machinist"},
                ]},
            }}}
        return httpx.Response(200, json={"data": response})

    ranked, skipped = accessible_ranked_sources(
        102, "bard", client_id="id", client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert ranked == (
        (1, ReportReference(anonymous_code, 22, 7)),
        (2, ReportReference("normal", 1, 7)),
    )
    assert skipped == ()


def test_ambiguous_anonymous_bards_are_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        if "EncounterRankings" in body["query"]:
            rows = [] if body["variables"].get("page", 1) > 1 else [
                {"name": "Anonymous", "report": {"code": "a:ambiguous", "fightID": 22}},
                {"name": "Known", "report": {"code": "known", "fightID": 1}},
            ]
            data = {"worldData": {"encounter": {
                "id": 102, "characterRankings": {"rankings": rows},
            }}}
        else:
            code = body["variables"]["code"]
            anonymous = code == "a:ambiguous"
            data = {"reportData": {"report": {
                "fights": [{"id": 22 if anonymous else 1,
                            "encounterID": 102,
                            "friendlyPlayers": [7, 9] if anonymous else [7]}],
                "masterData": {"actors": [
                    {"id": actor_id, "type": "Player", "subType": "Bard",
                     "name": f"Player ({actor_id})" if anonymous else "Known"}
                    for actor_id in ([7, 9] if anonymous else [7])
                ]},
            }}}
        return httpx.Response(200, json={"data": data})

    ranked, skipped = accessible_ranked_sources(
        102, "bard", client_id="id", client_secret="secret",
        transport=httpx.MockTransport(handler),
    )
    assert ranked == ((2, ReportReference("known", 1, 7)),)
    assert len(skipped) == 1 and skipped[0][0] == 1


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
