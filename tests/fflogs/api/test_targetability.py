"""Targetability updates must be fetched for the whole encounter."""

from typing import Any

import pytest

from ffxiv_potency.fflogs import FFLogsError
from ffxiv_potency.fflogs.download import _download_targetability_events
from ffxiv_potency.fflogs.reference import ReportReference


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(variables)
        assert "sourceID" not in query  # The boss is the source, not the player.
        page = len(self.calls)
        return {
            "reportData": {
                "report": {
                    "fights": [{"startTime": 10_000}],
                    "masterData": {"actors": [{"id": 5, "name": "Vamp Fatale"}]},
                    "events": {
                        "data": [
                            {
                                "type": "targetabilityupdate",
                                "timestamp": 78_000,
                                "sourceID": 5,
                                "targetable": int(page == 2),
                            }
                        ],
                        "nextPageTimestamp": 80_000 if page == 1 else None,
                    },
                }
            }
        }


def test_targetability_download_includes_encounter_events_across_pages() -> None:
    client = _Client()

    events = _download_targetability_events(client, ReportReference("Kn9vkBgZT3RPGxDf", 21, 4))

    assert [event["targetable"] for event in events] == [0, 1]
    assert all(event["sourceID"] == 5 for event in events)
    assert client.calls[0]["filter"] == 'type="targetabilityupdate" or type="death"'
    assert client.calls[1]["startTime"] == 80_000


def test_targetability_download_rejects_stalled_pagination() -> None:
    class _StalledClient(_Client):
        def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            result = super().graphql(query, variables)
            result["reportData"]["report"]["events"]["nextPageTimestamp"] = 80_000
            return result

    with pytest.raises(FFLogsError, match="targetability pagination"):
        _download_targetability_events(_StalledClient(), ReportReference("Kn9vkBgZT3RPGxDf", 21, 4))


def test_encounter_appearance_download_uses_all_players_and_stays_compact():
    from ffxiv_potency.fflogs.download import _download_encounter_damage

    class Client:
        def graphql(self, query, variables):
            assert variables["sourceID"] is None
            return {
                "reportData": {
                    "report": {
                        "events": {
                            "data": [
                                {
                                    "type": "damage",
                                    "timestamp": 10,
                                    "sourceID": 2,
                                    "targetID": 10,
                                    "amount": 100,
                                },
                                {
                                    "type": "damage",
                                    "timestamp": 20,
                                    "sourceID": 1,
                                    "targetID": 10,
                                    "amount": 100,
                                },
                                {
                                    "type": "damage",
                                    "timestamp": 30,
                                    "sourceID": 3,
                                    "targetID": 10,
                                    "amount": 100,
                                },
                                {
                                    "type": "damage",
                                    "timestamp": 40,
                                    "sourceID": 10,
                                    "targetID": 1,
                                    "amount": 100,
                                },
                                {
                                    "type": "calculateddamage",
                                    "timestamp": 5,
                                    "sourceID": 1,
                                    "targetID": 10,
                                    "amount": 100,
                                },
                            ],
                            "nextPageTimestamp": None,
                        }
                    }
                }
            }

    master = {
        "actors": [
            {"id": 1, "type": "Player"},
            {"id": 2, "type": "Player"},
            {"id": 3, "type": "NPC", "petOwner": 1},
            {"id": 10, "type": "NPC"},
        ]
    }
    events = _download_encounter_damage(Client(), ReportReference("abc123", 1, 1), master)
    assert len(events) == 1
    assert events[0]["timestamp"] == 10 and events[0]["sourceID"] == 2
