"""Refresh combat duration without replacing original downloaded boundaries."""

import json

import httpx
import pytest

from ffxiv_potency.fflogs.client import FFLogsError
from ffxiv_potency.fflogs.download import refresh_combat_time
from ffxiv_potency.fflogs.reference import ReportReference


@pytest.mark.parametrize('combat', [869887, None])
def test_refresh_retains_saved_metadata_and_records_nullable_combat_time(tmp_path, combat):
    saved = {'id': 24, 'startTime': 11974486, 'endTime': 12866730,
             'encounterID': 4550, 'reportStartTime': 1000, 'friendlyPlayers': [100]}
    path = tmp_path / 'fight.json'
    path.write_text(json.dumps(saved))

    def respond(request):
        if request.url.path == '/oauth/token':
            return httpx.Response(200, json={'access_token': 'test'})
        body = json.loads(request.content)
        assert 'combatTime' in body['query']
        assert body['variables']['fightIDs'] == [24]
        return httpx.Response(200, json={'data': {'reportData': {'report': {
            'fights': [{**saved, 'combatTime': combat}],
        }}}})

    refresh_combat_time(ReportReference('YnJGy1bqjzMDmvZh', 24, 100), tmp_path,
                        client_id='test', client_secret='test',
                        transport=httpx.MockTransport(respond))
    assert json.loads(path.read_text()) == {**saved, 'combatTime': combat}


def test_refresh_rejects_changed_boundaries_without_writing(tmp_path):
    saved = {'id': 24, 'startTime': 11974486, 'endTime': 12866730}
    path = tmp_path / 'fight.json'
    original = json.dumps(saved)
    path.write_text(original)

    def respond(request):
        if request.url.path == '/oauth/token':
            return httpx.Response(200, json={'access_token': 'test'})
        return httpx.Response(200, json={'data': {'reportData': {'report': {
            'fights': [{**saved, 'startTime': 11996843, 'combatTime': 869887}],
        }}}})

    with pytest.raises(FFLogsError, match='does not match'):
        refresh_combat_time(ReportReference('YnJGy1bqjzMDmvZh', 24, 100), tmp_path,
                            client_id='test', client_secret='test',
                            transport=httpx.MockTransport(respond))
    assert path.read_text() == original
