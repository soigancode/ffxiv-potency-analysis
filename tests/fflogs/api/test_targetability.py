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
        return {"reportData": {"report": {
            "fights": [{"startTime": 10_000}],
            "masterData": {"actors": [{"id": 5, "name": "Vamp Fatale"}]},
            "events": {
                "data": [{"type": "targetabilityupdate", "timestamp": 78_000,
                          "sourceID": 5, "targetable": int(page == 2)}],
                "nextPageTimestamp": 80_000 if page == 1 else None,
            },
        }}}


def test_targetability_download_includes_encounter_events_across_pages() -> None:
    client = _Client()

    events = _download_targetability_events(client, ReportReference("Kn9vkBgZT3RPGxDf", 21, 4))

    assert [event["targetable"] for event in events] == [0, 1]
    assert all(event["sourceID"] == 5 for event in events)
    assert client.calls[0]["filter"] == 'type="targetabilityupdate"'
    assert client.calls[1]["startTime"] == 80_000


def test_targetability_download_rejects_stalled_pagination() -> None:
    class _StalledClient(_Client):
        def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
            result = super().graphql(query, variables)
            result["reportData"]["report"]["events"]["nextPageTimestamp"] = 80_000
            return result

    with pytest.raises(FFLogsError, match="targetability pagination"):
        _download_targetability_events(
            _StalledClient(), ReportReference("Kn9vkBgZT3RPGxDf", 21, 4)
        )
