"""Independently audit supplied PLD another_merchants_tale logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['6GXNV2hj4pDBybRd/fight-4/source-36', 'YnJGy1bqjzMDmvZh/fight-24/source-100', 'xRLQdJ2qv7XFT4rA/fight-35/source-478']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_another_merchants_tale.zip", prefix)


def test_missing_riot_blade_bonus_matches_independent_normalized_damage(tmp_path):
    import json
    from pathlib import Path
    from statistics import median
    from zipfile import ZipFile

    from ffxiv_potency.analysis import analyze_saved_fight

    prefix = 'YnJGy1bqjzMDmvZh/fight-24/source-100'
    with ZipFile('tests/fixtures/logs/pld_another_merchants_tale.zip') as z:
        for member in z.namelist():
            if member.startswith(prefix + '/') and member.endswith('.json'):
                (tmp_path / Path(member).name).write_bytes(z.read(member))
    names = {a['gameID']: a['name'] for a in json.loads(
        (tmp_path / 'master-data.json').read_text())['abilities']}
    damage = json.loads((tmp_path / 'damage-events.json').read_text())
    unknown = next(e for e in damage if e.get('type') == 'damage'
                   and names.get(e.get('abilityGameID')) == 'Riot Blade'
                   and 'bonusPercent' not in e)
    fixed = {'Fast Blade': 220, 'Atonement': 460, 'Supplication': 500, 'Sepulchre': 540}

    def normalize(e):
        return e['amount'] / e.get('multiplier', 1) / (
            1.628 if e.get('hitType') == 2 else 1) / (1.25 if e.get('directHit') else 1)

    refs = [normalize(e) / fixed[names[e['abilityGameID']]] for e in damage
            if e.get('type') == 'damage' and e.get('sourceID') == 100
            and e.get('targetID') == unknown['targetID']
            and abs(e['timestamp'] - unknown['timestamp']) <= 60000
            and names.get(e.get('abilityGameID')) in fixed and not e.get('overkill')
            and e.get('amount', 0) > 0 and e.get('hitType') != 10
            and not any(s in str(e.get('buffs', '')).split('.')
                        for s in ('1000049', '1000043', '1000044', '1002911'))]
    assert len(refs) >= 3
    observed_potency = normalize(unknown) / median(refs)
    assert 170 * .935 <= observed_potency <= 170 * 1.065
    assert not 330 * .935 <= observed_potency <= 330 * 1.065
    r = analyze_saved_fight(tmp_path, Path('data/jobs/pld/7.4/actions.json'), use_cache=False)
    assert r.pld is not None and r.pld.combos is not None
    assert r.pld.combos.unconfirmed_hits == 0
    inferred = r.pld.combos.inferred[0]
    assert (inferred.name, inferred.comboed, inferred.potency_lost) == ('Riot Blade', False, 160)
    assert inferred.previous_gcd == 'Sepulchre'
    from ffxiv_potency.analysis.cache import _decode, _encode
    from ffxiv_potency.analysis.models import AnalysisResult

    assert _decode(json.loads(json.dumps(_encode(r))), AnalysisResult) == r


@pytest.mark.parametrize('metadata', ['fight', 'research'])
def test_recorded_amt_combat_time_corrects_all_report_timestamps(tmp_path, capsys, metadata):
    import json
    from pathlib import Path
    from zipfile import ZipFile

    from ffxiv_potency import cli
    from ffxiv_potency.analysis import analyze_saved_fight
    from ffxiv_potency.analysis.cache import _decode, _encode
    from ffxiv_potency.analysis.models import AnalysisResult

    prefix = 'YnJGy1bqjzMDmvZh/fight-24/source-100'
    with ZipFile('tests/fixtures/logs/pld_another_merchants_tale.zip') as archive:
        for member in archive.namelist():
            if member.startswith(prefix + '/') and member.endswith('.json'):
                (tmp_path / Path(member).name).write_bytes(archive.read(member))
    actions = Path('data/jobs/pld/7.4/actions.json')
    before = analyze_saved_fight(tmp_path, actions)
    path = tmp_path / 'fight.json'
    saved = json.loads(path.read_text())
    original_start = saved['startTime']
    recorded = {**saved, 'combatTime': 869887}
    if metadata == 'fight':
        path.write_text(json.dumps(recorded))
    else:
        (tmp_path / 'timeline-context.json').write_text(json.dumps({'fight': recorded}))
    after = analyze_saved_fight(tmp_path, actions)
    assert after.duration_seconds == 869.887
    assert after.combat_start_offset_seconds == 22.357
    assert after.potency_min == before.potency_min
    assert after.potency_max == before.potency_max
    assert after.actions == before.actions
    assert after.raw_damage_events == before.raw_damage_events
    assert after.hit_bonus == before.hit_bonus
    assert before.targetable_seconds is not None and after.targetable_seconds is not None
    assert after.targetable_seconds == pytest.approx(before.targetable_seconds - 22.357)
    assert after.pps_min == pytest.approx(after.potency_min / after.targetable_seconds)
    assert after.pld is not None and after.pld.combos is not None
    assert after.pld.combos.inferred[0].seconds == 275.918
    assert before.pld is not None
    assert after.pld.bursts[0].seconds == pytest.approx(before.pld.bursts[0].seconds - 22.357)
    assert after.execution is not None and before.execution is not None
    before_cd = {c.name: c.possible for c in before.execution.cooldowns}
    after_cd = {c.name: c.possible for c in after.execution.cooldowns}
    assert before_cd['Intervene'] == 31 and after_cd['Intervene'] == 30
    assert json.loads(path.read_text())['startTime'] == original_start
    assert _decode(json.loads(json.dumps(_encode(after))), AnalysisResult) == after
    assert analyze_saved_fight(tmp_path, actions) == after
    cli._print_analysis(after)
    output = capsys.readouterr().out
    assert 'Duration: 14m30s' in output
    assert '04m36s Sepulchre -> Riot Blade:' in output
    assert ('04m07s: Blade of Truth cast, no hit - '
            'target defeated before hit landed') in output
    assert '22.357s pre-pull excluded' in output
