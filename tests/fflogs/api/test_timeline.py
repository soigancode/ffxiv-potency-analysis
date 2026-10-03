"""Boundary research retains raw evidence without changing fight metadata."""

import json

import httpx
import pytest

from ffxiv_potency.fflogs.client import FFLogsClient, FFLogsError
from ffxiv_potency.fflogs.reference import ReportReference
from ffxiv_potency.fflogs.timeline import capture_timeline


def test_capture_timeline_requests_party_wide_markers_and_paginates():
    requests = []
    fight = {'id': 24, 'startTime': 10000, 'endTime': 90000,
             'combatTime': 57643, 'dungeonPulls': [{'startTime': 32357, 'endTime': 90000}]}

    def respond(request):
        if request.url.path == '/oauth/token':
            return httpx.Response(200, json={'access_token': 'test-token'})
        body = json.loads(request.content)
        requests.append(body)
        page = len(requests)
        return httpx.Response(200, json={'data': {'reportData': {'report': {
            'fights': [fight],
            'events': {'data': [{'type': 'dungeonstart' if page == 1 else 'encounterstart',
                                'timestamp': 10000 if page == 1 else 32357}],
                       'nextPageTimestamp': 30000 if page == 1 else None},
        }}}})

    with FFLogsClient('test', 'test', transport=httpx.MockTransport(respond)) as client:
        result = capture_timeline(client, ReportReference('YnJGy1bqjzMDmvZh', 24, 100))
    assert result['fight'] == fight
    assert [e['timestamp'] for e in result['events']] == [10000, 32357]
    assert requests[0]['variables']['startTime'] is None
    assert requests[1]['variables']['startTime'] == 30000
    assert 'sourceID' not in requests[0]['query']
    assert r'type=\"encounterstart\"' in requests[0]['query']


def test_capture_timeline_rejects_stalled_pagination():
    class StalledClient:
        def graphql(self, query, variables):
            return {'reportData': {'report': {
                'fights': [{'id': 24}],
                'events': {'data': [], 'nextPageTimestamp': 30000},
            }}}

    with pytest.raises(FFLogsError, match='pagination'):
        capture_timeline(StalledClient(), ReportReference('YnJGy1bqjzMDmvZh', 24, 100))


def test_capture_timeline_accepts_absent_markers_and_nullable_metadata():
    class EmptyClient:
        def graphql(self, query, variables):
            return {'reportData': {'report': {
                'fights': [{'id': 24, 'combatTime': None, 'dungeonPulls': None}],
                'events': {'data': [], 'nextPageTimestamp': None},
            }}}

    result = capture_timeline(EmptyClient(), ReportReference('YnJGy1bqjzMDmvZh', 24, 100))
    assert result['events'] == []
    assert result['fight']['combatTime'] is None
