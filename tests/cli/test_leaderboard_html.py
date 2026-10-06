"""One offline leaderboard contains full analyses and preserves rank provenance."""

from dataclasses import replace
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag

from ffxiv_potency import cli
from ffxiv_potency.analysis import AnalysisError, AnalysisResult, HitOutcomeSummary, PotionSummary
from ffxiv_potency.analysis.cache import _encode
from ffxiv_potency.fflogs import FFLogsError, ReportReference
from ffxiv_potency.html_report import (
    JOB_COLOURS,
    _leaderboard_sort_values,
    write_leaderboard_report,
)

from .helpers import _write_selected_log


def required_tag(document: BeautifulSoup | Tag, selector: str) -> Tag:
    tag = document.select_one(selector)
    assert tag is not None
    return tag


@pytest.fixture
def result():
    return AnalysisResult(
        fight_name='Dancing Mad', encounter_id=1085, source_name='First Player',
        ndps=100, rdps=100, duration_seconds=60, raw_damage_events=1,
        landed_damage_events=1, matched_damage_events=1, potency_min=1000, potency_max=1000,
        actions=(), auto_attacks=(), pet_deployments=(), hit_outcomes=HitOutcomeSummary(1, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
    )


@pytest.mark.parametrize('selection,filename', [
    (None, 'war_dmu_top.html'), ('1-5', 'war_dmu_1-5.html'),
    ('1,2,3,4,5', 'war_dmu_ranks-1-2-3-4-5.html'),
])
@pytest.mark.parametrize('progress_enabled', [False, True])
def test_leaderboard_html_reuses_analyses_and_lists_all_skips(
    tmp_path, monkeypatch, capsys, result, selection, filename, progress_enabled,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.sys.stderr, 'isatty', lambda: progress_enabled)
    refs = tuple((rank, ReportReference(code, 1, 1)) for rank, code in
                 ((1, 'abc123'), (3, 'bad123'), (4, 'fail123'), (5, 'def456')))
    for lookup in ('accessible_ranked_sources', 'ranked_sources_in_range', 'ranked_sources_at_positions'):
        monkeypatch.setattr(cli, lookup, lambda *_, **__: (refs, ((2, 'private report'),)))

    def resolve(url, output, *, announce, include_targetability):
        assert not announce and include_targetability
        ref = cli.parse_report_url(url)
        if ref.report_code == 'fail123':
            raise FFLogsError('download unavailable')
        directory = output / ref.report_code / 'fight-1/source-1'
        _write_selected_log(directory, 1, 'Warrior')
        return directory

    calls = []

    def analyze(directory, actions, *, gear):
        assert gear == 'relic_7_55'
        calls.append(directory.parent.parent.name)
        if directory.parent.parent.name == 'bad123':
            raise AnalysisError('incomplete resource evidence')
        return result if directory.parent.parent.name == 'abc123' else replace(
            result, source_name='Second Player', potency_min=900, potency_max=900)

    monkeypatch.setattr(cli, '_resolve_analysis_directory', resolve)
    monkeypatch.setattr(cli, '_actions_for_job', lambda *_: Path('actions.json'))
    monkeypatch.setattr(cli, '_verify_supported_fight', lambda _: None)
    monkeypatch.setattr(cli, 'analyze_saved_fight', analyze)
    before = _encode(result)
    args = ['fflogs', 'war', 'umad', *([selection] if selection else []),
            '--gear', 'relic_7_55', '--html']
    assert cli.main(args) == 0
    assert calls == ['abc123', 'bad123', 'def456']
    assert _encode(result) == before
    document = BeautifulSoup((tmp_path / 'reports' / filename).read_text(), 'html.parser')
    leaderboard = document.select_one('#leaderboard')
    assert leaderboard is not None
    rows = leaderboard.select('tbody tr')
    assert [row.select('td')[0].get_text() for row in rows] == ['1', '5']
    assert [row.select('td')[1].get_text() for row in rows] == ['First Player', 'Second Player']
    assert '16.67' in rows[0].get_text() and '-10.00%' in rows[1].get_text()
    assert 'Rank 2: private report' in leaderboard.get_text()
    assert 'Rank 3: incomplete resource evidence' in leaderboard.get_text()
    assert 'Rank 4: download unavailable' in leaderboard.get_text()
    reports = document.select('details.player-report')
    assert len(reports) == 2 and reports[0].has_attr('open') and not reports[1].has_attr('open')
    for report in reports:
        assert 'Execution summary' in report.get_text()
        assert 'Hit Bonus and Luck' in report.get_text()
        assert 'Action totals and auto-attacks' in report.get_text()
    assert f'Saved HTML report: reports/{filename}' in capsys.readouterr().out


def test_combined_report_has_unique_ids_local_navigation_and_safe_text(tmp_path, result):
    directories = [tmp_path / 'abc123/fight-1/source-1', tmp_path / 'def456/fight-1/source-1']
    for directory in directories:
        _write_selected_log(directory, 1, 'Warrior')
    results = [result, replace(result, source_name='<script>unsafe & player</script>')]
    output = tmp_path / 'combined.html'
    write_leaderboard_report(results, directories, [5, 1], ('PPS',), [('16.67',), ('16.67',)],
                             output, job='warrior', skipped=((3, '<img src=x onerror=alert(1)>'),))
    soup = BeautifulSoup(output.read_text(), 'html.parser')
    ids = []
    for tag in soup.select('[id]'):
        value = tag.get('id')
        assert isinstance(value, str)
        ids.append(value)
    assert len(ids) == len(set(ids))
    for link in soup.select('a[href^="#"]'):
        href = link.get('href')
        assert isinstance(href, str)
        assert soup.find(id=href[1:]) is not None
    for tag in soup.select('[aria-describedby], [aria-labelledby]'):
        for attribute in ('aria-describedby', 'aria-labelledby'):
            references = tag.get(attribute, '')
            assert isinstance(references, str)
            for value in references.split():
                assert soup.find(id=value) is not None
    assert len(soup.select('html')) == len(soup.select('body')) == len(soup.select('script')) == 1
    assert not soup.select('img, iframe, script[src], link[href]')
    assert '<script>unsafe & player</script>' in soup.get_text()
    assert 'report.open = true' in soup.select('script')[0].get_text()
    assert [row.select('td')[0].get_text() for row in soup.select('#leaderboard tbody tr')] == ['1', '5']
    assert required_tag(soup, '#leaderboard th:first-child').get('aria-sort') == 'ascending'


def test_export_failure_is_reported_by_leaderboard_command(tmp_path, monkeypatch, capsys, result):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / 'abc123/fight-1/source-1'
    _write_selected_log(directory, 1, 'Warrior')
    monkeypatch.setattr(cli, 'accessible_ranked_sources', lambda *_, **__: (
        ((1, ReportReference('abc123', 1, 1)),), ()))
    monkeypatch.setattr(cli, '_resolve_analysis_directory', lambda *_, **__: directory)
    monkeypatch.setattr(cli, '_actions_for_job', lambda *_: Path('actions.json'))
    monkeypatch.setattr(cli, '_verify_supported_fight', lambda _: None)
    monkeypatch.setattr(cli, 'analyze_saved_fight', lambda *_: result)
    (tmp_path / 'reports').write_text('not a directory')
    assert cli.main(['fflogs', 'war', 'dmu', '--html']) == 1
    assert 'error:' in capsys.readouterr().err


def test_anonymous_entry_hides_player_name_in_summary_and_full_analysis(tmp_path, result):
    directory = tmp_path / 'a-abc123/fight-1/source-1'
    _write_selected_log(directory, 1, 'Warrior')
    output = tmp_path / 'anonymous.html'
    write_leaderboard_report([result], [directory], [10], ('PPS',), [('16.67',)], output,
                             job='warrior')
    soup = BeautifulSoup(output.read_text(), 'html.parser')
    assert 'First Player' not in soup.get_text()
    assert required_tag(soup, '#leaderboard tbody td a').get_text() == 'Anonymous'
    assert 'Rank 10 - Anonymous' in required_tag(soup, '.player-report summary').get_text()


@pytest.mark.parametrize('job,subtype', [
    ('paladin', 'Paladin'), ('warrior', 'Warrior'), ('bard', 'Bard'),
    ('machinist', 'Machinist'), ('dancer', 'Dancer'),
])
def test_all_job_leaderboards_preserve_theme_and_potency_ranges(tmp_path, result, job, subtype):
    directory = tmp_path / 'abc123/fight-1/source-1'
    _write_selected_log(directory, 1, subtype)
    result = replace(result, potency_max=1200)
    output = tmp_path / 'report.html'
    write_leaderboard_report([result], [directory], [1], ('PPS',), [('16.67-20.00',)],
                             output, job=job)
    soup = BeautifulSoup(output.read_text(), 'html.parser')
    assert JOB_COLOURS[job] in required_tag(soup, 'style').get_text()
    assert required_tag(soup, '#leaderboard h2').get_text() == job.title() + ' / Dancing Mad Leaderboard'
    assert not soup.select('main > header')
    assert 'PPS: 16.67-20.00' in required_tag(soup, '.player-report summary').get_text()
    assert 'Hit Bonus and Luck' in required_tag(soup, '.player-report').get_text()


def test_player_section_menu_is_in_sidebar_and_notes_are_only_in_header_help(tmp_path, result):
    directories = [tmp_path / 'abc123/fight-1/source-1', tmp_path / 'def456/fight-1/source-1']
    for directory in directories:
        _write_selected_log(directory, 1, 'Warrior')
    notes = ('Notes: KO deaths | DD Damage Downs | G ghosted hits (HP locks excluded)',
             '~ Targetable time estimated from recorded enemy windows.')
    output = tmp_path / 'report.html'
    write_leaderboard_report([result, result], directories, [1, 3], ('Notes',),
                             [('Gx1',), ('-',)], output, job='warrior', notes=notes)
    soup = BeautifulSoup(output.read_text(), 'html.parser')
    menus = soup.select('aside .sidebar-player')
    assert len(menus) == 2 and menus[0].has_attr('open')
    for index, menu in enumerate(menus, 1):
        links = menu.select(':scope > nav > a')
        assert any(link.get_text() == 'Execution summary' for link in links)
        assert any(link.get_text() == 'Hit Bonus and Luck' for link in links)
        assert all(str(link.get('href')).startswith(f'#player-{index}-section-') for link in links)
    assert not soup.select('.player-body nav')
    header = required_tag(soup, '#leaderboard th abbr[data-help]')
    assert header.get_text() == 'Notes (?)'
    assert str(header.get('title')).splitlines() == [
        '- KO: Deaths', '- DD: Damage Downs', '- G: Ghosted hits (HP locks excluded)',
        '- ~ Targetable time estimated from recorded enemy windows.',
    ]
    for note in notes:
        assert note not in required_tag(soup, '#leaderboard').get_text()
    script = required_tag(soup, 'script').get_text()
    assert 'menu.dataset.player === report.id' in script
    assert "window.addEventListener('scroll'" in script
    assert 'th abbr[data-help][title]' in script


def test_sort_values_use_numeric_ranges_and_calendar_dates(tmp_path, result):
    directory = tmp_path / 'abc123/fight-1/source-1'
    _write_selected_log(directory, 1, 'Warrior')
    baseline = result
    ranged = replace(result, duration_seconds=3600, targetable_seconds=1000,
                     potency_min=1200, potency_max=1800, ndps=None, rdps=12345.6)
    values = _leaderboard_sort_values(ranged, baseline, directory)
    assert values['Duration'] == 3600
    assert values['Targetable'] == 1000
    assert values['Potency'] == 1500
    assert values['PPS'] == 1.5
    assert values['rDPS/nDPS'] == 12345.6
    assert values['Date'] == 739737  # 1 May 2026, stored as an ordinal.
    assert _leaderboard_sort_values(baseline, baseline, directory)['dPPS'] == 0
    missing = _leaderboard_sort_values(replace(result, rdps=None, ndps=None), baseline, tmp_path)
    assert missing['Targetable'] is None and missing['Date'] is None
    assert missing['rDPS/nDPS'] is None


def test_sortable_headers_metadata_and_section_highlighting(tmp_path, result):
    directory = tmp_path / 'abc123/fight-1/source-1'
    _write_selected_log(directory, 1, 'Warrior')
    labels = ('Duration', 'Targetable', 'rDPS/nDPS', 'Potency', 'PPS', 'dPPS', 'aHB', 'aLuck', 'Notes', 'Date')
    row = ('01m 00s', 'n/a', '100.0', '1,000', '16.67', '-', '+0.00%', '0.00%', '-', '01/05/26')
    output = tmp_path / 'report.html'
    write_leaderboard_report([result], [directory], [1], labels, [row], output, job='warrior',
                             metadata=('Partition: 1', 'Patch: 7.5'))
    soup = BeautifulSoup(output.read_text(), 'html.parser')
    buttons = soup.select('#leaderboard th button[data-sort-column]')
    assert [button.get_text().removesuffix(' (?)') for button in buttons] == [
        'Rank', *(label for label in labels if label != 'Notes')]
    metadata = soup.select('#leaderboard .metadata')
    assert len(metadata) == 1 and metadata[0].get_text() == 'Patch: 7.5 | Partition: 1 | Ranked by rDPS'
    assert all(not button.has_attr('title') for button in buttons)
    for button in buttons:
        label = button.get_text().removesuffix(' (?)')
        abbreviation = button.select_one('abbr')
        if label in {'dPPS', 'aHB', 'aLuck', 'HB', 'PPS'}:
            assert abbreviation is not None
            assert abbreviation.has_attr('title')
            assert button.select_one('.header-help-cue') is not None
        else:
            assert abbreviation is None
            assert button.select_one('.header-help-cue') is None
    assert 'Ranges sort by their midpoint' not in str(soup)
    assert 'Sort by ' not in str(soup)
    cells = soup.select('#leaderboard tbody td')
    assert cells[0].get('data-sort-value') == '1'
    assert buttons[0].get('data-sort-column') == '0'
    assert required_tag(soup, '#leaderboard th:first-child').get('aria-sort') == 'ascending'
    assert cells[2].get('data-sort-value') == '60'
    assert not cells[3].has_attr('data-sort-value')
    assert cells[7].get('data-sort-value') == '0'
    assert cells[-1].get('data-sort-value') == '739737'
    script = required_tag(soup, 'script').get_text()
    assert "setAttribute('aria-current', 'location')" in script
    assert "'ascending' : 'descending'" in script
    assert 'body.appendChild(row)' in script
    css = required_tag(soup, 'style').get_text()
    assert 'tbody tr:hover td:first-child{background:#24272b}' in css
    assert 'nav a[aria-current=location]' in css
    assert '#leaderboard h2,.leaderboard-link{color:var(--accent-text)}' in css
    assert '#leaderboard .table-wrap,#leaderboard table{width:100%}' in css
    assert 'main{border-top:3px solid var(--accent);padding-top:24px}' in css
    assert 'body{border-top:3px solid var(--accent)}' not in css
    assert '#leaderboard{border-top:3px solid var(--accent)}' not in css
