"""Existing AMT downloads acquire combat-time metadata once when credentials exist."""

import json

import pytest

from ffxiv_potency import cli


@pytest.mark.parametrize('encounter,metadata,credentials,expected', [
    (4550, 'missing', True, True),
    (4550, 'missing', False, False),
    (4550, 'fight', True, False),
    (4550, 'research', True, False),
    (4549, 'missing', True, False),
    (4551, 'missing', True, False),
])
def test_saved_amt_refresh_is_scoped_and_preserves_boundaries(
    tmp_path, monkeypatch, encounter, metadata, credentials, expected,
):
    directory = tmp_path / 'YnJGy1bqjzMDmvZh/fight-24/source-100'
    directory.mkdir(parents=True)
    fight = {'id': 24, 'encounterID': encounter, 'startTime': 10000, 'endTime': 90000,
             'friendlyPlayers': [100]}
    if metadata == 'fight':
        fight['combatTime'] = None
    for name in cli._SAVED_FIGHT_FILES:
        (directory / name).write_text(json.dumps(fight if name == 'fight.json' else []))
    for name in ['combatant-info-events.json', 'life-events.json', 'revival-buff-events.json']:
        (directory / name).write_text('[]')
    (directory / 'rankings.json').write_text(json.dumps({'metric': 'ndps', 'rdps': {}, 'dps': {}}))
    if metadata == 'research':
        (directory / 'timeline-context.json').write_text(json.dumps({
            'fight': {**fight, 'combatTime': 57643},
        }))
    if credentials:
        monkeypatch.setenv('FFLOGS_CLIENT_ID', 'test')
        monkeypatch.setenv('FFLOGS_CLIENT_SECRET', 'test')
    calls = []

    def refresh(reference, path):
        calls.append(reference)
        assert path == directory
        (path / 'fight.json').write_text(json.dumps({**fight, 'combatTime': 57643}))

    monkeypatch.setattr(cli, 'refresh_combat_time', refresh)
    assert cli._resolve_analysis_directory(str(directory), tmp_path) == directory
    assert bool(calls) == expected
    assert json.loads((directory / 'fight.json').read_text())['startTime'] == 10000
    assert cli._resolve_analysis_directory(str(directory), tmp_path) == directory
    assert len(calls) == int(expected)
