import json

import httpx
import pytest

from ffxiv_potency.fflogs.client import FFLogsError
from ffxiv_potency.fflogs.selection import ReportFight, ReportPlayer, report_fights


def test_report_fights_uses_each_fights_player_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        body = json.loads(request.content)
        assert body["variables"] == {"code": "abc123"}
        assert "ReportChoices" in body["query"]
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [
                {"id": 9, "name": "Boss", "encounterID": 101,
                 "startTime": 1000, "endTime": 121000, "kill": False,
                 "friendlyPlayers": [18, 20, 30]},
                {"id": 10, "name": "Boss", "encounterID": 101,
                 "startTime": 130000, "endTime": 190000, "kill": True,
                 "friendlyPlayers": [20]},
                {"id": 11, "name": "Trash", "encounterID": None,
                 "friendlyPlayers": [18]},
                {"id": 12, "name": "Trash", "encounterID": 0},
            ],
            "masterData": {"actors": [
                {"id": 18, "name": "Alice", "type": "Player", "subType": "Bard"},
                {"id": 20, "name": "Bob", "type": "Player", "subType": "Machinist"},
                {"id": 30, "name": "Pet", "type": "Pet", "subType": "Machinist"},
            ]},
        }}}})

    assert report_fights(
        "abc123", client_id="id", client_secret="secret", transport=httpx.MockTransport(handler),
    ) == (
        ReportFight(9, "Boss", 101, 120.0, False,
                    (ReportPlayer(18, "Alice", "Bard"),
                     ReportPlayer(20, "Bob", "Machinist"))),
        ReportFight(10, "Boss", 101, 60.0, True,
                    (ReportPlayer(20, "Bob", "Machinist"),)),
    )


def test_report_fights_rejects_missing_participants() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(200, json={"data": {"reportData": {"report": {
            "fights": [{"id": 9, "name": "Boss", "encounterID": 101}],
            "masterData": {"actors": []},
        }}}})

    with pytest.raises(FFLogsError, match="fight 9 has no player participants"):
        report_fights(
            "abc123", client_id="id", client_secret="secret",
            transport=httpx.MockTransport(handler),
        )
