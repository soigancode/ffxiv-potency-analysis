"""Verify shared reporting and hidden combo fields against saved Dancing Mad fights."""

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from bs4 import BeautifulSoup

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.models import AnalysisResult
from ffxiv_potency.cli import _print_analysis
from ffxiv_potency.html_report import render_html_report
from ffxiv_potency.report_document import ReportTable, collect_report

CASES = [
    ('war', 'war_dancing_mad.zip', 'c8rZPQjqBd9LKGzv/fight-19/source-71', 'Maim'),
    ('mch', 'mch_dancing_mad_ultimate.zip', 'GaAKTpkz4dLq6Qrb/fight-14/source-14', 'Heated Clean Shot'),
    ('dnc', 'dnc_dancing_mad.zip', 'VWJv7x9DbRa4ktH6/fight-7/source-4', 'Fountain'),
]

POTION_CASES = [
    ('pld', 'pld_dancing_mad.zip', 'dzyx6FtjcQXMDJP3/fight-13/source-98'),
    ('war', 'war_dancing_mad.zip', 'c8rZPQjqBd9LKGzv/fight-19/source-71'),
    ('brd', 'brd_dancing_mad.zip', None),
    ('mch', 'mch_dancing_mad_ultimate.zip', 'GaAKTpkz4dLq6Qrb/fight-14/source-14'),
    ('dnc', 'dnc_dancing_mad.zip', 'VWJv7x9DbRa4ktH6/fight-7/source-4'),
]


@pytest.mark.parametrize('job,archive,prefix', POTION_CASES)
def test_potion_window_totals_reconcile_for_every_job(tmp_path, job, archive, prefix, capsys):
    if prefix is None:
        with ZipFile(Path('tests/fixtures/logs') / archive) as logs:
            prefix = next(m.rsplit('/', 1)[0] for m in logs.namelist() if m.endswith('/fight.json'))
    extract(tmp_path, archive, prefix)
    result = analyze_saved_fight(tmp_path, Path(f'data/jobs/{job}/7.4/actions.json'), use_cache=False)
    potion = result.potion
    assert len(potion.window_totals) == len(potion.windows) == potion.uses
    assert potion.uses > 0
    for total_field, summary_field in (
        ('base_potency_min', 'potted_potency_min'),
        ('base_potency_max', 'potted_potency_max'),
        ('gained_potency_min', 'gained_potency_min'),
        ('gained_potency_max', 'gained_potency_max'),
    ):
        assert sum(getattr(t, total_field) for t in potion.window_totals) == pytest.approx(
            getattr(potion, summary_field))
    assert _decode(json.loads(json.dumps(_encode(result))), AnalysisResult) == result
    encoded = _encode(result)
    _print_analysis(result)
    report = capsys.readouterr().out
    assert _encode(result) == encoded
    headings = ('Execution summary', 'Deaths and damage penalties', 'Cooldowns and burst windows',
                'Combos, ready effects and charges', 'Melee downtime', 'Potions',
                'Ghosted attacks and reduced hits', 'Hit Bonus and Luck', 'Action totals and auto-attacks',
                'Data and assumptions')
    present = [f'\n{name}:\n' for name in headings if f'\n{name}:\n' in report]
    assert [report.index(h) for h in present] == sorted(report.index(h) for h in present)
    assert all(report.count(h) == 1 for h in present)
    assert 'Cooldowns and burst windows:\n' in report
    assert 'Combos, ready effects and charges:\n' in report
    assert '\nAuto-attacks:' not in report
    assert '\n  Auto-attacks:\n    ' in report
    if result.pld or result.brd_dots:
        assert '\nDoTs:' not in report
        assert report.index('Action totals and auto-attacks:') < report.index('\n  DoTs:') < report.index('\n  Auto-attacks:')
        dots = report.split('\n  DoTs:\n', 1)[1].split('\n  Auto-attacks:', 1)[0]
        assert 'Periodic potency  Total potency' in dots
        if result.pld:
            expected = result.pld.circle.application_potency + result.pld.circle.tick_potency
            assert f'{expected:,.1f}' in dots
            assert '  Total potency:' not in dots
        else:
            periodic = [dot for dot in result.brd_dots if dot.name != 'Iron Jaws']
            expected = sum(dot.direct_potency + dot.tick_potency for dot in periodic)
            if len(periodic) > 1:
                assert f'  Total potency: {expected:,.1f}' in dots
            else:
                assert '  Total potency:' not in dots
    output = report.split('Potions:\n')[1].split('\n\n', 1)[0]
    assert output.startswith('  Item: ')
    assert output.splitlines()[1].startswith('    Potion ')
    assert all(line.startswith('    ') for line in output.splitlines()[2:2 + potion.uses])
    assert 'Base potency' in output and 'Potion gain' in output
    assert 'Window 1:' not in output
    assert output.count('Landed damage with a potion snapshot') == 1
    with collect_report() as blocks:
        _print_analysis(result)
    html = BeautifulSoup(render_html_report(result), 'html.parser')
    assert 'DoTs' not in [heading.get_text() for heading in html.select('main h2')]
    if result.pld or result.brd_dots:
        heading = html.find('h2', string='Action totals and auto-attacks')
        assert heading is not None
        section = heading.parent
        assert section is not None
        assert section.find('h3', string='DoTs') is not None
    tables = [block for block in blocks if isinstance(block, ReportTable)]
    assert len(html.select('table')) == len(tables)
    for rendered, block in zip(html.select('table'), tables):
        assert [cell.get_text() for cell in rendered.select('thead th')] == list(block.labels)
        rendered_rows = [row for row in rendered.select('tbody tr') if not row.select('.row-note')]
        if rendered.has_attr('data-sortable'):
            # HTML cooldown timing is pre-sorted. Compare each row with its
            # original presentation event rather than requiring console order.
            rendered_rows.sort(key=lambda row: int(str(row['data-original-order'])))
        rows = [[cell.get_text() for cell in row.select('td')] for row in rendered_rows]
        if block.labels == ('Time', 'GCD sequence'):
            rows = [[time, sequence.replace('→', '->')] for time, sequence in rows]
        assert rows == [list(row) for row in block.rows]
    assert _encode(result) == encoded


def extract(directory, archive, prefix):
    with ZipFile(Path('tests/fixtures/logs') / archive) as logs:
        for member in logs.namelist():
            if member.startswith(prefix + '/') and member.endswith('.json'):
                (directory / Path(member).name).write_bytes(logs.read(member))


def test_dancer_cooldown_availability_matches_saved_cutscene(tmp_path):
    from ffxiv_potency.analysis.availability import action_lock_windows, available_windows
    from ffxiv_potency.analysis.execution import summarize_execution
    from ffxiv_potency.analysis.targetability import TargetableTime

    extract(tmp_path, 'dnc_dancing_mad.zip', 'VWJv7x9DbRa4ktH6/fight-7/source-4')

    def load(name):
        return json.loads((tmp_path / name).read_text())

    fight = load('fight.json')
    start, end = fight['startTime'], fight['endTime']
    names = {a['gameID']: a['name'] for a in load('master-data.json')['abilities']}
    actions = {a['name']: a for a in json.loads(Path('data/jobs/dnc/7.4/actions.json').read_text())['actions']}
    debuffs = load('debuff-events.json')
    combatants = load('combatant-info-events.json')
    locks = action_lock_windows(debuffs, combatants, names, 4, start, end)
    assert locks
    windows = available_windows(((start, end),), locks, start, end)
    result = summarize_execution('dancer', load('cast-events.json'), load('damage-events.json'),
        load('buff-events.json'), debuffs, load('life-events.json'), combatants, names, actions,
        {}, 4, start, end, TargetableTime(0, 'unused for self buffs'), {})
    # Independent single-charge replay: advance by the recast after each use,
    # jumping to the end of a lock when the next use cannot occur yet.
    for cooldown in result.cooldowns:
        ready = start
        expected = 0
        for begin, finish in windows:
            ready = max(ready, begin)
            while ready < finish:
                expected += 1
                ready += actions[cooldown.name]['recast_seconds'] * 1000
        assert cooldown.possible == expected
        assert cooldown.basis == 'action availability'
    assert _decode(json.loads(json.dumps(_encode(result))), type(result)) == result


@pytest.mark.parametrize('job,archive,prefix,combo', CASES)
def test_missing_combo_field_restores_recorded_real_log_potency_and_resources(
        tmp_path, job, archive, prefix, combo, capsys):
    extract(tmp_path, archive, prefix)
    actions = Path(f'data/jobs/{job}/7.4/actions.json')
    baseline = analyze_saved_fight(tmp_path, actions, use_cache=False)
    names = {a['gameID']: a['name'] for a in json.loads(
        (tmp_path / 'master-data.json').read_text())['abilities']}
    path = tmp_path / 'damage-events.json'
    damage = json.loads(path.read_text())
    source = int(prefix.rsplit('source-', 1)[1])
    candidates = [e for e in damage if e.get('type') == 'damage'
                  and e.get('sourceID') == source and names.get(e.get('abilityGameID')) == combo
                  and e.get('bonusPercent', 0) > 0 and not e.get('overkill')
                  and e.get('targetResources', {}).get('hitPoints') not in {0, 1}]
    assert candidates
    # Several physical reference hits are needed; choose a non-opening packet.
    chosen = candidates[len(candidates) // 2]
    for event in damage:
        if (event.get('packetID'), event.get('abilityGameID')) == (chosen.get('packetID'), chosen.get('abilityGameID')):
            event.pop('bonusPercent', None)
    path.write_text(json.dumps(damage))
    result = analyze_saved_fight(tmp_path, actions, use_cache=False)
    assert result.combos is not None
    assert any(i.name == combo and i.comboed for i in result.combos.inferred)
    assert result.actions == baseline.actions
    assert result.pps_min == baseline.pps_min and result.pps_max == baseline.pps_max
    assert result.potion == baseline.potion
    assert result.pet_deployments == baseline.pet_deployments
    assert result.dnc_procs == baseline.dnc_procs
    assert result.luck_score == baseline.luck_score
    assert _decode(json.loads(json.dumps(_encode(result))), AnalysisResult) == result
    _print_analysis(result)
    output = capsys.readouterr().out
    assert '  Cooldown timing:' in output
    if job == 'war':
        assert 'IR spenders = Fell Cleave/Decimate using Inner Release charges.' not in output
        assert result.burst_alignment == ()
    else:
        assert 'Completion compares recorded potency with the best feasible action order.' in output
    assert 'Combos, ready effects and charges:' in output


def test_bard_snapshot_alignment_matches_independent_raging_strikes_arithmetic(tmp_path):
    with ZipFile('tests/fixtures/logs/brd_dancing_mad.zip') as logs:
        prefix = next(m.rsplit('/', 1)[0] for m in logs.namelist() if m.endswith('/fight.json'))
    extract(tmp_path, 'brd_dancing_mad.zip', prefix)
    result = analyze_saved_fight(tmp_path, Path('data/jobs/brd/7.4/actions.json'), use_cache=False)
    alignment = result.burst_alignment[0]
    # Damage buff potency is included in the ordinary totals, but removed from
    # alignment's inside column. Scope totals must reconcile independently.
    scope_total = sum((a.potency_min + a.potency_max) / 2 for a in result.actions
                      if a.name in alignment.scope)
    assert alignment.inside_potency * 1.15 + alignment.outside_potency == pytest.approx(scope_total)
    assert sum(r.potential_gain for r in alignment.outside) == pytest.approx(alignment.outside_potency * .15)
    assert _decode(json.loads(json.dumps(_encode(result))), AnalysisResult) == result
