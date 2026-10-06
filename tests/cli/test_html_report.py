"""HTML export, escaping, shared report content and output isolation."""

import json
from dataclasses import replace

import pytest
from bs4 import BeautifulSoup, Tag

from ffxiv_potency import cli
from ffxiv_potency.analysis.burst_opportunities import (
    BurstAction,
    BurstWindow,
    HeldCast,
    HoldAction,
    HoldComparison,
)
from ffxiv_potency.analysis.cache import _encode
from ffxiv_potency.analysis.cooldown_timing import CooldownTiming
from ffxiv_potency.analysis.diagnostic_types import FollowUpContext
from ffxiv_potency.analysis.execution import CooldownUse, ExecutionSummary
from ffxiv_potency.analysis.models import (
    ActionSummary,
    AnalysisResult,
    ConsumableIdentity,
    HitOutcomeSummary,
    PotionSummary,
    PotionWindow,
    PotionWindowTotal,
    ReducedDamageHit,
)
from ffxiv_potency.analysis.penalties import DamagePenaltySummary, StatusWindow
from ffxiv_potency.analysis.pld.burst_opportunities import BURST_ACTIONS
from ffxiv_potency.analysis.pld.follow_ups import PldFollowUpIssue
from ffxiv_potency.analysis.pld.summary import PldBurst, PldDotSummary, PldFollowUp, PldSummary
from ffxiv_potency.analysis.war.bursts import WarBurst, WarPotionBurst
from ffxiv_potency.analysis.war.summary import WarSummary
from ffxiv_potency.html_report import (
    _SECTION_NAV_SCRIPT,
    _TABLE_HOVER_SCRIPT,
    _TABLE_SORT_SCRIPT,
    _TOOLTIP_SCRIPT,
    JOB_COLOURS,
    _indent_sequence_abilities,
    _line,
    _table,
    render_html_report,
)
from ffxiv_potency.report_document import ReportTable, ReportText, collect_report, emit_text
from ffxiv_potency.reporting import (
    add_followup_tooltips,
    package_completion_needs_note,
    package_completion_note,
    pld_followup_context,
    print_burst_opportunities,
    print_cooldown_timing,
    print_pld_followup_context,
)

from .helpers import _write_selected_log


def test_cooldown_timing_charge_explanation_is_an_action_tooltip():
    with collect_report() as blocks:
        print_cooldown_timing((CooldownTiming('Intervene', 8.2, 2.7, True),
                               CooldownTiming('Expiacion', 10.0, 1.0)))
    block = next(block for block in blocks if isinstance(block, ReportTable))
    soup = BeautifulSoup(_table(block), 'html.parser')
    cells = soup.select('tbody tr:last-child td')
    assert cells[0].get_text() == 'Intervene'
    assert cells[0].get('title') == 'Confirmed time at full charges. Actual time may be longer.'
    assert cells[0].get('data-state') == 'info'
    assert not soup.select('tr.needs-attention')
    assert not soup.select('tbody tr:first-child td[title]')
    assert [block.text for block in blocks if isinstance(block, ReportText)][-1] == (
        '  Timing starts at first use and counts usable time while alive. Delays may align with buffs.'
    )


@pytest.mark.parametrize('potency,state', [(1000, 'info'), (1300, 'shortfall')])
def test_completion_tooltip_preserves_chronological_action_orders(potency, state):
    actions = tuple(BurstAction(name, int(name in {'Blade of Honor', 'Intervene'}),
                               int(name == 'Intervene'), int(name in {'Blade of Honor', 'Intervene'}))
                    for name in BURST_ACTIONS)
    window = BurstWindow(360, 380, actions, 1000, 1000, potency,
        recorded_order=(('Intervene', 372.292), ('Blade of Honor', 372.963)),
        proposed_order=(('Blade of Honor', 372.369), ('Intervene', 373.069)))
    with collect_report() as blocks:
        print_burst_opportunities((window,), str)
    block = next(block for block in blocks if isinstance(block, ReportTable))
    cell = BeautifulSoup(_table(block), 'html.parser').select('tbody tr:first-child td')[-1]
    if state == 'info':
        assert cell.get_text() == '100.0%'
        assert not cell.has_attr('title')
        assert not cell.has_attr('data-state')
        return
    assert cell['data-state'] == state
    assert 'Recorded order:\n- 06m 12.292s Intervene\n- 06m 12.963s Blade of Honor' in cell['title']
    assert 'Proposed order:\n- 06m 12.369s Blade of Honor\n- 06m 13.069s Intervene' in cell['title']
    assert 'Selected package:' not in cell['title']
    assert cell['title'].count('Recorded / proposed potency:') == 1
    assert 'landed base potency.' not in cell['title']


def test_completion_tooltip_places_boundaries_in_both_action_sequences():
    from ffxiv_potency.reporting import package_completion_note

    window = BurstWindow(360, 380, (BurstAction('Blade of Honor', 1, 0, 1),), 0, 0, 1000,
        recorded_order=(('Guardian', 367.339), ('Blade of Honor', 372.963)),
        proposed_order=(('Blade of Honor', 372.369),),
        boundary_events=(('HP lock reached: Kefka', 373.812), ('Untargetable: Kefka', 377)))
    note = package_completion_note(window)
    assert note.count('06m 13.812s HP lock reached: Kefka') == 2
    assert note.count('06m 17.000s Untargetable: Kefka') == 2
    assert 'Other abilities stay in roughly the same weave slots.' in note
    assert 'Recorded order:\n- 06m 07.339s Guardian' in note
    assert 'Proposed order:\n- 06m 12.369s Blade of Honor' in note


def test_uncertain_completion_order_is_marked_for_review():
    actions = tuple(BurstAction(name, 0, 0, int(name == 'Blade of Honor')) for name in BURST_ACTIONS)
    window = BurstWindow(0, 10, actions, 1000, 1000, 1000,
        proposed_order=(('Blade of Honor', 1.0),),
        comparison_notes=('Requiescat timing needs review.',))
    with collect_report() as blocks:
        print_burst_opportunities((window,), str)
    block = next(block for block in blocks if isinstance(block, ReportTable))
    cell = BeautifulSoup(_table(block), 'html.parser').select('tbody tr:first-child td')[-1]
    assert cell['data-state'] == 'review'
    assert 'Requiescat timing needs review.' in cell['title']
    assert 'falls short' not in cell['title']


def required_tag(document: BeautifulSoup | Tag, selector: str) -> Tag:
    tag = document.select_one(selector)
    assert tag is not None, f"Missing HTML element: {selector}"
    return tag


@pytest.mark.parametrize('action_label', ['Action', 'Pet action'])
def test_action_totals_have_numeric_sort_keys_and_three_sortable_headers(action_label):
    block = ReportTable((action_label, 'Uses', 'Hits/ticks', 'Landed potency'),
                        (('First', '10', '1,234', '1,000-2,000'),
                         ('Second', '-', '2', '50')), (), '  ')
    soup = BeautifulSoup(_table(block), 'html.parser')
    assert required_tag(soup, 'table').has_attr('data-sortable')
    assert [button.get_text() for button in soup.select('th button')] == [
        'Uses', 'Hits/ticks', 'Landed potency']
    assert required_tag(soup, 'th:last-child')['aria-sort'] == 'descending'
    assert [cell.get('data-sort-value') for cell in soup.select('tbody tr:first-child td')] == [
        None, '10.0', '1234.0', '1500.0']
    assert not required_tag(soup, 'tbody tr:last-child td:nth-child(2)').has_attr('data-sort-value')


@pytest.mark.parametrize('labels,rows', [
    (('Metric', 'Baseline', 'Recorded', 'Adjusted'),
     (('Hit Bonus', '-', '+48.00%', '+45.00%'), ('Luck', '24.98%', '42.31%', '40.12%'))),
    (('Outcome', 'Gear baseline', 'Observed', 'Difference', 'Hits'),
     (('Normal Hit', '60.00%', '50.00%', '-10.00 pp', '5'),
      ('Direct Hit', '20.00%', '30.00%', '+10.00 pp', '3'))),
])
def test_hit_statistics_sort_every_column_and_restore_original_order(labels, rows):
    soup = BeautifulSoup(_table(ReportTable(labels, rows, (), '  ')), 'html.parser')
    assert [button.get_text() for button in soup.select('th button')] == list(labels)
    assert required_tag(soup, 'th:first-child')['aria-sort'] == 'ascending'
    assert [cell.get('data-sort-value') for cell in soup.select('tbody td:first-child')] == ['0', '1']
    if labels[0] == 'Outcome':
        assert [cell.get('data-sort-value') for cell in soup.select('tbody td:nth-child(4)')] == ['-10.0', '10.0']
    else:
        assert 'other players' in required_tag(soup, 'th:last-child abbr')['title']
        baseline_cells = soup.select('tbody td:nth-child(2)')
        assert not baseline_cells[0].has_attr('data-sort-value')
        assert baseline_cells[1]['data-sort-value'] == '24.98'


def test_potion_table_sorts_potion_number_potency_and_gain_numerically():
    block = ReportTable(('Potion', 'Start', 'End', 'Base potency', 'Potion gain'),
                        (('1', '00m 10s', '00m 40s', '1,000.0-2,000.0', '100.0-200.0'),
                         ('2', '02m 10s', '02m 40s', '0.0', '0.0')), (), '    ')
    soup = BeautifulSoup(_table(block), 'html.parser')
    assert required_tag(soup, 'table[data-potions]').has_attr('data-sortable')
    assert [button.get_text() for button in soup.select('th button')] == ['Potion', 'Base potency', 'Potion gain']
    assert required_tag(soup, 'th:first-child')['aria-sort'] == 'ascending'
    assert [cell.get('data-sort-value') for cell in soup.select('tbody tr:first-child td')] == [
        '1.0', None, None, '1500.0', '150.0']
    assert required_tag(soup, 'tbody tr:last-child td:last-child')['data-sort-value'] == '0.0'
    assert 'DoT ticks and auto-attacks' in required_tag(soup, 'th:nth-child(4) abbr')['title']


def test_cooldown_timing_sorts_numeric_seconds_and_keeps_unavailable_values_missing():
    block = ReportTable(('Action', 'Ready while usable', 'Longest delay'),
                        (('Intervene', '9.9s', '2.7s'), ('Expiacion', '100.0s', '10.0s'),
                         ('Imperator', 'n/a', 'n/a')), (), '  ')
    soup = BeautifulSoup(_table(block), 'html.parser')
    assert required_tag(soup, 'table').has_attr('data-sortable')
    assert [button.get_text() for button in soup.select('th button')] == [
        'Ready while usable', 'Longest delay']
    rows = soup.select('tbody tr')
    assert [[cell.get('data-sort-value') for cell in row.select('td')[1:]] for row in rows] == [
        ['100.0', '10.0'], ['9.9', '2.7'], [None, None]]
    assert [row.select('td')[0].get_text() for row in rows] == ['Expiacion', 'Intervene', 'Imperator']
    assert required_tag(soup, 'th:nth-child(2)').get('aria-sort') == 'descending'
    assert required_tag(soup, 'th:nth-child(3)').get('aria-sort') == 'none'


def test_cooldown_opportunities_stay_in_report_but_not_section_menu(result):
    result = replace(result, execution=ExecutionSummary(
        'paladin', (CooldownUse('Intervene', 1, 2),), (), (), ()))
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    heading = next(h for h in soup.select('main h3')
                   if h.get_text().startswith('Cooldown opportunities'))
    button = required_tag(heading, 'button')
    assert button.get_text() == '(?)'
    tooltip = required_tag(heading, '[role="tooltip"]')
    assert tooltip.get('id') == button.get('aria-describedby')
    assert tooltip.get_text() == (
        'Possible uses account for downtime and cutscenes. Cooldowns recover throughout. '
        'Self buffs can be used before bosses become targetable.')
    assert 'full-duration upper bound' not in soup.get_text()
    assert not any('Cooldown opportunities' in a.get_text() for a in soup.select('aside a'))
    assert 'table[data-sortable] td:not(:first-child){text-align:right}' in required_tag(soup, 'style').get_text()


def test_crosshair_is_limited_to_burst_completion_and_landed_hits(result, monkeypatch):
    from ffxiv_potency.reporting import table

    def report(*args, **kwargs):
        emit_text('Cooldowns and burst windows:')
        for title in ('Cooldown timing', 'Burst completion', 'Landed hits and potency',
                      'Potion burst completion', 'Spell casts'):
            emit_text('  ' + title + ':')
            table(('Action', 'Hits'), [('Imperator', '1')])
        emit_text('Action totals and auto-attacks:')
        table(('Action', 'Uses', 'Hits/ticks', 'Landed potency'), [('Imperator', '1', '1', '580')])

    monkeypatch.setattr('ffxiv_potency.html_report.print_analysis', report)
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    highlighted = soup.select('table[data-crosshair]')
    assert len(highlighted) == 2
    headings = []
    for highlighted_table in highlighted:
        heading = highlighted_table.find_previous('h3')
        assert isinstance(heading, Tag)
        headings.append(heading.get_text())
    assert headings == ['Burst completion', 'Landed hits and potency']
    assert not required_tag(soup, 'table[data-sortable]').has_attr('data-crosshair')
    assert "querySelectorAll('main table[data-crosshair]')" in _TABLE_HOVER_SCRIPT


def test_melee_downtime_action_names_on_hover_preserve_cast_evidence_and_escape_text():
    line = '    02m 44s: HS (instant) -> 3.47s -> HS (hard-cast) -> SL -> T <target>'
    soup = BeautifulSoup(_line(line, action_names=True), 'html.parser')
    assert soup.get_text() == line.strip()
    assert [tag['title'] for tag in soup.select('abbr')] == [
        'Holy Spirit', 'Holy Spirit', 'Shield Lob', 'Tomahawk']
    assert not soup.select('target')
    assert not BeautifulSoup(_line(line), 'html.parser').select('abbr')


def test_ranged_chain_table_keeps_gaps_visible_and_action_names_on_hover(result, monkeypatch):
    from ffxiv_potency.reporting import table

    def report(*args, **kwargs):
        emit_text('Melee downtime:')
        emit_text('  3 ranged GCDs in 1 chain.')
        table(('Time', 'GCD sequence'), [('02m 42s',
              'Fast Blade -> 2.50s -> HS (hard-cast) -> 2.51s -> SL -> 2.49s -> HS (hard-cast) -> 2.50s -> Riot Blade')])

    monkeypatch.setattr('ffxiv_potency.html_report.print_analysis', report)
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    chain = required_tag(soup, 'table[data-ranged-chains]')
    assert len(chain.select('tbody tr')) == 1
    assert [gap.get_text() for gap in chain.select('.chain-gap')] == ['2.50s', '2.51s', '2.49s', '2.50s']
    assert [action.get_text() for action in chain.select('.chain-ranged')] == ['HS (hard-cast)', 'SL', 'HS (hard-cast)']
    assert [name.get('title') for name in chain.select('abbr')] == ['Holy Spirit', 'Shield Lob', 'Holy Spirit']
    assert 'Fast Blade' in chain.get_text() and 'Riot Blade' in chain.get_text()


def test_missing_and_reduced_hit_tables_preserve_reasons_and_numeric_time_sorting(result):
    result = replace(result,
        ghosted=(('Unknown', 1), ('Downtime', 1), ('Locked', 1), ('Environment', 1)),
        ghosted_times=(('Unknown', (10,)), ('Downtime', (20,)), ('Locked', (30,)), ('Environment', (40,))),
        ghosted_targets=(('Unknown', ((10, 'Boss'),)), ('Downtime', ((20, 'Boss'),))),
        ghosted_ending_times=(('Downtime', ((20, 'target became untargetable before hit landed'),)),
                              ('Locked', ((30, 'phase HP lock'),)), ('Environment', ((40, 'downtime'),))),
        reduced_damage_hits=(ReducedDamageHit(600, 'Late', 1, 99, 'Boss'),
                             ReducedDamageHit(119, 'Early', 2, 98, 'Boss')))
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    section = next(section for section in soup.select('section')
                   if required_tag(section, 'h2').get_text() == 'Ghosted attacks and reduced hits')
    assert [heading.get_text() for heading in section.select('h3')] == [
        'Ghosted hits', 'HP locks and downtime', 'Reduced-damage hits']
    tables = section.select('table')
    assert len(tables) == 3
    assert all(not table.has_attr('data-sortable') for table in tables[:2])
    assert 'reason unconfirmed' in tables[0].get_text()
    assert 'untargetable' in tables[0].get_text()
    assert 'phase HP lock' in tables[1].get_text() and 'untargetable' not in tables[1].get_text()
    assert 'Environment' in tables[1].get_text()
    assert [button.get_text() for button in tables[2].select('th button')] == ['Time', 'Damage retained']
    assert required_tag(tables[2], 'th')['aria-sort'] == 'ascending'
    assert [cell.get('data-sort-value') for cell in tables[2].select('tbody td:first-child')] == ['119', '600']
    retained = tables[2].select('tbody td:last-child')
    assert [cell.get('data-sort-value') for cell in retained] == ['2.0', '1.0']
    assert '2/100 damage.' in retained[0]['title']


def test_death_table_distinguishes_recorded_inferred_and_missing_revivals(result):
    result = replace(result, status_windows=(
        StatusWindow('Dead', 1, 12, 'resurrected'),
        StatusWindow('Dead', 20, 35, 'revived by next cast; exact time unknown'),
        StatusWindow('Dead', 40, 60, 'fight ended'),
    ))
    before = _encode(result)
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    section = next(section for section in soup.select('section')
                   if required_tag(section, 'h2').get_text() == 'Deaths and damage penalties')
    rows = [[cell.get_text() for cell in row.select('td')] for row in section.select('tbody tr')]
    assert rows == [
        ['1', '00m 01s', '00m 12s', '11.0s', 'Recorded revival'],
        ['2', '00m 20s', '00m 35s', '<= 15.0s', 'Next cast'],
        ['3', '00m 40s', '-', '20.0s', 'Dead at fight end'],
    ]
    assert section.get_text().count('may be overstated') == 1
    assert _encode(result) == before


@pytest.fixture
def result():
    return AnalysisResult(
        fight_name="Test fight", encounter_id=1, source_name="Test Player", ndps=None,
        duration_seconds=60, raw_damage_events=1, landed_damage_events=1,
        matched_damage_events=1, potency_min=700, potency_max=700,
        actions=(ActionSummary("Test action", 1, 700, 700, uses=1),),
        auto_attacks=(), pet_deployments=(), hit_outcomes=HitOutcomeSummary(1, 0, 0, 0),
        potion=PotionSummary(
            1, 700, 700, 50, 50, windows=(PotionWindow(0, 30),),
            window_totals=(PotionWindowTotal(700, 700, 50, 50),),
            item=ConsumableIdentity("Grade 4 Gemdraught of Strength [HQ]", recorded=True),
        ),
        unmatched=(), ghosted=(),
    )


@pytest.mark.parametrize("job", JOB_COLOURS)
def test_html_uses_job_palette_and_preserves_report_tables(result, job, capsys):
    result = replace(result, execution=ExecutionSummary(job, (), (), (), ()))
    before = _encode(result)
    with collect_report() as blocks:
        cli._print_analysis(result)
    document = render_html_report(result)
    assert capsys.readouterr().out == ""
    assert _encode(result) == before
    soup = BeautifulSoup(document, "html.parser")
    assert f"--accent:{JOB_COLOURS[job]}" in required_tag(soup, "style").get_text()
    tables = [block for block in blocks if isinstance(block, ReportTable)]
    assert len(soup.select("table")) == len(tables)
    assert not soup.select('main .spacer + h3')
    assert not soup.select('main section > h2 + .spacer, main section > .spacer:last-child')
    for table, block in zip(soup.select("table"), tables):
        assert [th.get_text() for th in table.select("thead th")] == list(block.labels)
        assert [[td.get_text() for td in row.select("td")]
                for row in table.select("tbody tr") if not row.select(".row-note")] == [
                    list(row) for row in block.rows]
    assert "Item: Grade 4 Gemdraught of Strength [HQ]" in soup.get_text()
    assert not soup.select("script[src], link[href], img[src], iframe")
    assert soup.select_one('meta[name="viewport"]')
    links = soup.select("aside nav a")
    headings = soup.select("main h2, main h3[id], main details summary")
    assert [a.get_text() for a in links] == [h.get_text() for h in headings]
    for link in links:
        target = required_tag(soup, str(link.get('href')))
        assert target.get_text().startswith(link.get_text())
    for menu in soup.select('aside .nav-section'):
        assert required_tag(menu, 'summary a').get_text() == 'Cooldowns and burst windows'
        subsection_links = menu.select(':scope > nav > a')
        assert subsection_links
        section = required_tag(soup, '#' + str(menu.get('data-section')))
        assert [a.get('href') for a in subsection_links] == [
            '#' + str(h.get('id')) for h in section.select('h3[id]')]
    for link in links:
        href = link["href"]
        assert isinstance(href, str)
        required_tag(soup, href)
    cli._print_analysis(result)
    assert "Player: Test Player" in capsys.readouterr().out


def test_html_escapes_log_content_and_preserves_anonymity(result):
    result = replace(result, source_name='<script>alert("player")</script>',
                     fight_name='</title><img src="x" onerror="alert(1)">',
                     actions=(ActionSummary('<svg onload="alert(2)">', 1, 700, 700),))
    document = render_html_report(result)
    soup = BeautifulSoup(document, "html.parser")
    assert not soup.select("img, svg")
    scripts = soup.select('script')
    assert len(scripts) == 1 and scripts[0].string == (
        _TOOLTIP_SCRIPT + _SECTION_NAV_SCRIPT + _TABLE_HOVER_SCRIPT + _TABLE_SORT_SCRIPT)
    tooltip = required_tag(soup, '#action-tooltip')
    assert tooltip.parent == soup.body
    assert tooltip['role'] == 'tooltip' and tooltip.has_attr('hidden')
    assert required_tag(soup, "h1").get_text() == result.source_name
    assert required_tag(soup, "title").get_text().startswith(result.source_name)
    assert result.fight_name in soup.get_text()
    anonymous = BeautifulSoup(render_html_report(result, anonymous=True), "html.parser")
    assert required_tag(anonymous, "h1").get_text() == "Anonymous"
    assert result.source_name not in anonymous.get_text()


def test_anonymous_html_does_not_inherit_terminal_italics(result, monkeypatch):
    monkeypatch.setattr(cli.sys.stdout, 'isatty', lambda: True)
    document = render_html_report(result, anonymous=True)
    assert required_tag(BeautifulSoup(document, 'html.parser'), 'h1').get_text() == 'Anonymous'
    assert '\x1b' not in document


def test_metric_help_is_keyboard_accessible_in_the_table(result):
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    assert required_tag(soup, 'td abbr[title*="Extra damage"]')['tabindex'] == '0'
    baseline = required_tag(soup, 'th abbr[title*="Expected Luck"]')
    assert baseline['tabindex'] == '0'
    assert 'before rate buffs' in baseline['title']
    assert 'Luck baseline:' not in soup.get_text()
    assert 'including guaranteed hits' in required_tag(soup, 'td abbr[title*="Extra damage"]')['title']


@pytest.mark.parametrize('rank', [3, '~614'])
def test_html_shows_saved_individual_rank_and_explicit_rank_takes_precedence(tmp_path, result, rank):
    directory = tmp_path / 'source-18'
    _write_selected_log(directory, 18)
    character = {'name': 'Test Player', 'class': 'Machinist', 'rank': rank}
    payload = {'rdps': {'data': [{'fightID': 1, 'roles': {'dps': {'characters': [
        character, {**character, 'id_2': 99, 'rank': 1},
    ]}}}]}}
    (directory / 'rankings.json').write_text(json.dumps(payload))
    html = BeautifulSoup(render_html_report(result, directory=directory), 'html.parser')
    assert required_tag(html, '.eyebrow').get_text() == f'MCH / Saved rank {rank}'
    explicit = BeautifulSoup(render_html_report(result, directory=directory, rank=2), 'html.parser')
    assert required_tag(explicit, '.eyebrow').get_text() == 'MCH / Rank 2'
    payload['rdps']['data'][0]['fightID'] = 2
    (directory / 'rankings.json').write_text(json.dumps(payload))
    unknown = BeautifulSoup(render_html_report(result, directory=directory), 'html.parser')
    assert required_tag(unknown, '.eyebrow').get_text() == 'MCH'


def test_html_omits_ambiguous_saved_rank(tmp_path, result):
    directory = tmp_path / 'source-18'
    _write_selected_log(directory, 18)
    characters = [{'name': 'Test Player', 'class': 'Machinist', 'rank': rank} for rank in (1, 2)]
    (directory / 'rankings.json').write_text(json.dumps({
        'rdps': {'data': [{'fightID': 1, 'roles': {'dps': {'characters': characters}}}]},
    }))
    html = BeautifulSoup(render_html_report(result, directory=directory), 'html.parser')
    assert required_tag(html, '.eyebrow').get_text() == 'MCH'


@pytest.mark.parametrize('encounter,short', [(1085, 'DMU'), (4550, 'AMT'), (101, 'M9S')])
def test_html_tab_uses_canonical_fight_shorthand(result, encounter, short):
    result = replace(result, encounter_id=encounter, fight_name='Long boss names')
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    assert required_tag(soup, "title").get_text() == f'Test Player - {short} | FFXIV Potency Analysis'
    if encounter == 1085:
        assert cli._format_fight(result) == 'Dancing Mad (dmu)'


def test_burst_shortfalls_and_unknown_expectations_remain_distinct():
    block = ReportTable(("Burst", "Buff start", "Buff end", "Imperator", "Honor", "Intervene"),
                        (("1", "00m 00s", "00m 20s", "0/1", "1/?", "2/2"),),
                        ('<missing hit>\nReason unknown',), "  ")
    soup = BeautifulSoup(_table(block), "html.parser")
    assert required_tag(soup, '[data-state="shortfall"]').get_text() == "0/1"
    assert required_tag(soup, '[data-state="unknown"]').get_text() == "1/?"
    assert len(soup.select("[data-state]")) == 2
    assert "<missing hit>" in soup.get_text()
    assert not soup.select("missing")
    assert required_tag(soup, ".row-note")["colspan"] == "6"


def test_report_collection_restores_output_after_failure(capsys):
    with collect_report() as outer:
        emit_text("outer")
        with pytest.raises(ValueError), collect_report() as inner:
            emit_text("inner")
            raise ValueError("render failed")
        emit_text("restored")
    assert outer == [ReportText("outer"), ReportText("restored")]
    assert inner == [ReportText("inner")]
    emit_text("terminal")
    assert capsys.readouterr().out == "terminal\n"


def test_missing_burst_hits_are_flagged_in_both_tables_without_flagging_cleaves():
    actions = tuple(BurstAction(name, 1, 0 if name == 'Blade of Honor' else 2, 1)
                    for name in ('Imperator', 'Goring Blade', 'Confiteor', 'Blade of Faith',
                                 'Blade of Truth', 'Blade of Valor', 'Blade of Honor',
                                 'Circle of Scorn', 'Expiacion', 'Intervene'))
    with collect_report() as blocks:
        print_burst_opportunities((BurstWindow(0, 20, actions, 1000),), lambda t: f'{t}s')
    tables = [block for block in blocks if isinstance(block, ReportTable)]
    assert len(tables) == 2
    for block, expected in zip(tables, ('1/1', '0')):
        soup = BeautifulSoup(_table(block), 'html.parser')
        cells = soup.select('[data-state="missing-hit"]')
        assert len(cells) == 1
        cell = cells[0]
        assert cell.get_text() == expected
        assert 'Blade of Honor' in cell['title']
        assert 'landed hits' in cell['title']
        assert cell['tabindex'] == '0'
        assert 'Honor:' in cell['aria-label']
        assert len(soup.select('tr.needs-attention')) == 1
        assert soup.select_one('.attention-key')


@pytest.mark.parametrize('potion', [False, True])
def test_displaced_goring_tooltip_explains_honor_tradeoff_before_hp_lock(potion):
    from ffxiv_potency.reporting import print_job_packages

    names = ('Imperator', 'Goring Blade', 'Confiteor', 'Blade of Faith',
             'Blade of Truth', 'Blade of Valor', 'Blade of Honor',
             'Circle of Scorn', 'Expiacion', 'Intervene')
    actions = tuple(BurstAction(name, 1, 0 if name == 'Blade of Honor' else 1,
                               0 if name == 'Goring Blade' else 1) for name in names)
    window = BurstWindow(364, 384, actions, 7755, 5810, 6110)
    context = ((375, 'Blade of Honor', 'Kefka', 'phase HP lock'),)
    with collect_report() as blocks:
        if potion:
            print_job_packages((('Potion', (window,)),), str, hit_context=context)
        else:
            print_burst_opportunities((window,), str, hit_context=context)
    block = next(block for block in blocks if isinstance(block, ReportTable))
    soup = BeautifulSoup(_table(block), 'html.parser')
    cell = soup.select('tbody tr')[0].select('td')[block.labels.index('Goring')]
    assert cell.get_text() == '1/0'
    assert 'Recorded: 1 cast.\nComparison: 0 casts.' in cell['title']
    assert 'See Completion for the package comparison.' in cell['title']
    assert 'omitting' not in cell['title']
    completion = soup.select('tbody tr')[0].select('td')[-1]
    assert 'Estimated gain: 300.0 base potency.' in completion['title']


def test_later_hp_lock_ghosts_are_not_package_shortfalls():
    names = ('Imperator', 'Goring Blade', 'Confiteor', 'Blade of Faith',
             'Blade of Truth', 'Blade of Valor', 'Blade of Honor',
             'Circle of Scorn', 'Expiacion', 'Intervene')
    actions = tuple(
        BurstAction(name, 1 if name != 'Intervene' else 2,
                    0 if name in {'Goring Blade', 'Blade of Honor'} else 1,
                    0 if name == 'Goring Blade' else 1,
                    ('1 later HP-lock cast excluded from comparison; occurred after the first ghost.',)
                    if name in {'Goring Blade', 'Intervene'} else (),
                    excluded_casts=int(name in {'Goring Blade', 'Intervene'}))
        for name in names
    )
    with collect_report() as blocks:
        print_burst_opportunities((BurstWindow(0, 20, actions, 1000, 1000, 1300),), str)
    block = next(block for block in blocks if isinstance(block, ReportTable))
    cells = BeautifulSoup(_table(block), 'html.parser').select('tbody tr:first-child td')
    for name, ratio in (('Goring', '0/0'), ('Intervene', '1/1')):
        cell = cells[block.labels.index(name)]
        assert cell.get_text() == ratio
        assert cell.get('data-state') == 'info'
        assert cell.get('title') == (
            'Excluded from comparison: cast after the first hit blocked by the HP lock.')
    assert cells[block.labels.index('Honor')].get('data-state') == 'missing-hit'


def test_pld_potion_columns_follow_display_sequence_without_changing_cached_results():
    from ffxiv_potency.reporting import PLD_POTION_ACTIONS, print_job_packages

    names = ('Intervene', 'Blade of Honor', 'Confiteor', 'Imperator',
             'Blade of Valor', 'Goring Blade', 'Blade of Truth', 'Blade of Faith',
             'Expiacion', 'Circle of Scorn')
    window = BurstWindow(0, 20, tuple(BurstAction(name, 1, 1, 1) for name in names), 1000)
    before = _encode(window)
    with collect_report() as blocks:
        print_job_packages((('Potion', (window,)),), str, action_order=PLD_POTION_ACTIONS)
    block = next(block for block in blocks if isinstance(block, ReportTable))
    assert block.labels == ('Burst', 'Start', 'End', 'Goring', 'Imperator', 'Scorn', 'Confiteor',
                            'Expiacion', 'Intervene', 'Faith', 'Truth', 'Valor', 'Honor', 'Completion')
    assert _encode(window) == before


@pytest.mark.parametrize('job, names', [
    ('paladin', {'Goring': 'Goring Blade', 'Faith': 'Blade of Faith',
                 'Truth': 'Blade of Truth', 'Valor': 'Blade of Valor',
                 'Honor': 'Blade of Honor', 'Scorn': 'Circle of Scorn'}),
    ('warrior', {'IR spenders': 'Fell Cleave / Decimate using Inner Release charges',
                 'NC': 'Inner Chaos / Chaotic Cyclone (Nascent Chaos)',
                 'Rend': 'Primal Rend', 'Ruination': 'Primal Ruination',
                 'Wrath': 'Primal Wrath', 'Upheaval': 'Upheaval / Orogeny'}),
])
def test_action_header_names_replace_report_definitions(job, names, result, monkeypatch, capsys):
    action_names = (
        ('Imperator', 'Goring Blade', 'Confiteor', 'Blade of Faith', 'Blade of Truth',
         'Blade of Valor', 'Blade of Honor', 'Circle of Scorn', 'Expiacion', 'Intervene')
        if job == 'paladin' else
        ('IR spenders', 'Infuriate', 'Nascent Chaos', 'Primal Rend', 'Primal Ruination',
         'Primal Wrath', 'Upheaval/Orogeny', 'Onslaught'))
    actions = tuple(BurstAction(name, 1, 1, 1) for name in action_names)

    def report(*args, **kwargs):
        emit_text('\nCooldowns and burst windows:')
        print_burst_opportunities((BurstWindow(0, 20, actions, 1000),), str, job=job)

    monkeypatch.setattr('ffxiv_potency.html_report.print_analysis', report)
    report()
    console = capsys.readouterr().out
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    definitions = ('Goring =', 'Scorn =') if job == 'paladin' else (
        'IR spenders =', 'NC =', 'Rend, Ruination and Wrath refer', 'Upheaval includes')
    for definition in definitions:
        assert definition not in console
        assert definition not in soup.get_text()
    for label, full_name in names.items():
        headers = [tag for tag in soup.select('th abbr') if tag.get_text() == label]
        assert len(headers) == 2
        for header in headers:
            assert header['title'] == full_name
            assert header['aria-label'] == full_name
            assert header['tabindex'] == '0'
    assert ('Hits count actions granted by each burst' if job == 'paladin'
            else 'Hits include later impacts') in soup.get_text()


def test_burst_completion_caps_extra_casts_and_keeps_unknown_expectations_unscored():
    windows = (
        BurstWindow(0, 20, (BurstAction('Imperator', 2, 2, 1),
                           BurstAction('Blade of Honor', 0, 0, 1)), 1000),
        BurstWindow(120, 140, (BurstAction('Imperator', 1, 1, 1),
                               BurstAction('Blade of Honor', 1, 0, 1)), 1000),
        BurstWindow(240, 260, (BurstAction('Imperator', 1, 1, None),), 1000),
        BurstWindow(360, 380, (BurstAction('Imperator', 0, 0, 0),), 0),
    )
    with collect_report() as blocks:
        print_burst_opportunities(windows, lambda t: f'{t}s')
    table = next(block for block in blocks if isinstance(block, ReportTable))
    assert table.labels[-1] == 'Completion'
    assert [row[-1] for row in table.rows] == ['50.0%', '100.0%', 'n/a', 'n/a']


def test_shared_package_explanations_appear_once_after_first_table():
    from ffxiv_potency.reporting import print_job_packages

    window = BurstWindow(0, 20, (BurstAction('Imperator', 1, 1, 1),), 1000, 1000, 1200)
    explanations = set()
    with collect_report() as blocks:
        print_burst_opportunities((window,), str, explanations=explanations)
        print_job_packages((('Potion', (window,)),), str, explanations=explanations)
    texts = [block.text for block in blocks if isinstance(block, ReportText)]
    assert sum('Cells show recorded casts / proposed casts.' in text for text in texts) == 1
    assert sum('Completion compares recorded potency with the best feasible action order.' in text for text in texts) == 1
    tables = [block for block in blocks if isinstance(block, ReportTable) and block.labels[-1] == 'Completion']
    assert all(table.rows[0][-1] == '83.3%' for table in tables)
    assert all('Recorded / proposed potency: 1,000.0 / 1,200.0.' in str(table.cell_notes) for table in tables)


def test_spell_table_sorts_spells_by_existing_priority_and_casts_numerically():
    block = ReportTable(('Spell', 'Enhancement', 'Cast evidence', 'Casts'), (
        ('Blade of Faith', 'Requiescat', 'instant', '12'),
        ('Holy Spirit', 'Divine Might', 'instant', '100'),
        ('Holy Spirit', 'Requiescat', 'instant', '2'),
        ('Holy Spirit', 'None', 'opener', '1'),
    ), (), 2)
    soup = BeautifulSoup(_table(block), 'html.parser')
    table = soup.select_one('table')
    assert table is not None and table.has_attr('data-spells')
    headers = table.select('th')
    assert headers[0]['aria-sort'] == 'ascending'
    assert [b['data-sort-column'] for b in table.select('th button')] == ['0', '3']
    rows = table.select('tbody tr')
    assert [r.select('td')[0]['data-sort-value'] for r in rows] == ['0', '1', '1', '1']
    assert [r.select('td')[3]['data-sort-value'] for r in rows] == ['12.0', '100.0', '2.0', '1.0']


@pytest.mark.parametrize('name,label', [
    ('Blade of Honor', 'Honor'), ('Pitch Perfect', 'PP'),
    ('Full Metal Field', 'Full Metal'), ('Dance of the Dawn', 'Dawn'),
])
def test_shared_package_headers_keep_full_action_names_on_hover(name, label):
    from ffxiv_potency.reporting import print_job_packages

    window = BurstWindow(0, 20, (BurstAction(name, 1, 1, 1),), 1000, 1000, 1000)
    with collect_report() as blocks:
        print_job_packages((('Potion', (window,)),), str)
    table = next(block for block in blocks if isinstance(block, ReportTable))
    soup = BeautifulSoup(_table(table), 'html.parser')
    header = soup.find('abbr', string=label)
    assert isinstance(header, Tag)
    assert header['title'] == header['aria-label'] == name


def test_missing_hits_move_to_followup_context_without_duplicates(result):
    reason = 'target became untargetable before hit landed'
    result = replace(result, ghosted_times=(('Expiacion', (14.0, 200.0)),),
                     ghosted_ending_times=(('Expiacion', ((14.0, reason), (200.0, reason))),),
                     ghosted_targets=(('Expiacion', ((14.0, 'Kefka'), (200.0, 'Kefka'))),))
    actions = tuple(BurstAction(name, 1, 0 if name == 'Expiacion' else 1, 1)
                    for name in ('Imperator', 'Goring Blade', 'Confiteor', 'Blade of Faith',
                                 'Blade of Truth', 'Blade of Valor', 'Blade of Honor',
                                 'Circle of Scorn', 'Expiacion', 'Intervene'))
    with collect_report() as blocks:
        windows = (BurstWindow(0, 20, actions, 1000),)
        stamp = lambda t: f'{t:.0f}s'
        print_burst_opportunities(windows, stamp)
        bursts = (PldBurst(0, 'Imperator', (), (), (
            PldFollowUpIssue(('Expiacion',), 'no_hit', 'downtime'),
            PldFollowUpIssue(('Blade of Truth',), 'missing_cast', 'unconfirmed'),
        )),)
        print_pld_followup_context(bursts, windows, result, stamp)
    hits_index = next(i for i, block in enumerate(blocks)
                      if isinstance(block, ReportTable) and block.labels[-1] == 'Landed potency')
    after_table = blocks[hits_index + 1]
    assert isinstance(after_table, ReportText)
    assert after_table.text.startswith('  Hits count actions granted by each burst')
    context_index = blocks.index(ReportText('\n  Follow-up context:'))
    assert ReportText(f'    14s Expiacion on Kefka ({reason})') in blocks[context_index + 1:]
    assert not any(isinstance(block, ReportText) and 'Expiacion cast, no hit' in block.text for block in blocks)
    assert ReportText('    Burst 0s: Blade of Truth missing - reason unconfirmed') in blocks
    assert not any(isinstance(block, ReportText) and '200s Expiacion' in block.text for block in blocks)


def test_pld_followup_context_appears_in_table_tooltips_and_console_list(result, capsys):
    names = ('Imperator', 'Goring Blade', 'Confiteor', 'Blade of Faith', 'Blade of Truth',
             'Blade of Valor', 'Blade of Honor', 'Circle of Scorn', 'Expiacion', 'Intervene')
    actions = tuple(BurstAction(name, 0 if name == 'Blade of Truth' else 1,
                               0 if name in {'Blade of Truth', 'Blade of Honor'} else 1, 1)
                    for name in names)
    window = BurstWindow(0, 20, actions, 1000)
    burst = PldBurst(0, 'Imperator', (), ('Recorded sequence note',), (
        PldFollowUpIssue(('Blade of Honor',), 'no_hit', 'phase HP lock'),
        PldFollowUpIssue(('Blade of Truth',), 'missing_cast', 'expiry', 'Requiescat charges'),
    ))
    pld = PldSummary((), (), (burst,), (), PldDotSummary(0, 0, 0, 0),
                     burst_opportunities=(window,))
    result = replace(result, pld=pld, burst_packages=(('Potion', (window,)),),
                     ghosted_times=(('Blade of Honor', (14.0,)),),
                     ghosted_ending_times=(('Blade of Honor', ((14.0, 'phase HP lock'),)),),
                     ghosted_targets=(('Blade of Honor', ((14.0, 'Kefka'),)),))
    before = _encode(result)
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    assert 'Follow-up context' not in soup.get_text()
    tables = [table for table in soup.select('table')
              if any(th.get_text() in {'Honor', 'Truth'} for th in table.select('th'))]
    assert len(tables) == 3
    for table in tables:
        headers = [th.get_text() for th in table.select('th')]
        cells = table.select('tbody tr')[0].select('td')
        honor_note = cells[headers.index('Honor')]['title']
        assert isinstance(honor_note, str)
        assert honor_note.startswith('First hit blocked by the HP lock.')
        assert '00m 14s Blade of Honor on Kefka' in honor_note
        assert 'Blade of Truth missing - Requiescat charges expired' in cells[headers.index('Truth')]['title']
        assert 'Recorded sequence note' in cells[0 if headers[-1] == 'Landed potency' else 1]['title']
    cli._print_analysis(result)
    console = capsys.readouterr().out
    assert 'Follow-up context:' in console
    assert console.count('First hit blocked by the HP lock.') == 1
    assert console.count('00m 14s Blade of Honor on Kefka') == 1
    assert _encode(result) == before


def test_joint_hold_table_is_available_on_completed_burst_tooltip():
    comparison = HoldComparison((
        HoldAction('Blade of Valor', 1250, 700, 700, 35, 2, 'None'),
        HoldAction('Blade of Honor', 1250, 1890, 1890, 50, 2, 'None'),
    ), 2500, 2590, 2590)
    window = BurstWindow(0, 20, tuple(BurstAction(name, 1, 1, 1) for name in BURST_ACTIONS),
                         0, 2590, 2590, hold_comparison=comparison, attributed_followups=True)
    before = _encode(window)
    with collect_report() as blocks:
        print_burst_opportunities((window,), str)
    table = next(b for b in blocks if isinstance(b, ReportTable) and b.labels[-1] == 'Completion')
    soup = BeautifulSoup(_table(table), 'html.parser')
    cell = soup.select('tbody td')[-1]
    assert cell.get_text() == '100.0%'
    assert 'Action | Inside FoF | Held' in cell['title']
    assert 'Total | 2,500.0 | 2,590.0' in cell['title']
    assert 'Holding gained 90.0 potency.' in cell['title']
    assert "table.className = 'hold-comparison'" in _TOOLTIP_SCRIPT
    assert _encode(window) == before


def test_order_tooltips_label_held_and_carried_actions_without_renaming_them():
    source = BurstWindow(0, 20, (), 0, recorded_order=(('Blade of Honor', 50),),
        proposed_order=(('Blade of Honor', 50),), held_casts=(HeldCast('Blade of Honor', 50, 2),))
    note = package_completion_note(source)
    assert '50.000s Blade of Honor (Held)' in note
    assert '50.000s Blade of Honor (Hold)' in note
    recipient = replace(source, start_seconds=45, end_seconds=65, held_casts=(),
                        carried_casts=(HeldCast('Blade of Honor', 50, 2),))
    note = package_completion_note(recipient)
    assert note.count('Blade of Honor (from the previous window)') == 2
    assert 'Blade of Honor (Held)' not in note


def test_held_action_labels_preserve_ability_indentation():
    note = ('Recorded order:\n- 07m 43.870s Blade of Valor (Held)\n'
            '- 08m 08.228s Blade of Honor (Held)\nProposed order:\n'
            '- 08m 08.228s Blade of Honor (Hold)\n'
            '- 08m 08.228s Blade of Honor (from the previous window)')
    formatted = _indent_sequence_abilities(note, {'Blade of Honor'})
    assert '- 07m 43.870s Blade of Valor (Held)' in formatted
    assert formatted.count('-   08m 08.228s Blade of Honor') == 3


def test_rounded_zero_package_gain_does_not_create_a_completion_tooltip():
    window = BurstWindow(0, 20, (), 0, 6811.3, 6811.300001)
    assert not package_completion_needs_note(window)
    assert 'Estimated gain:' not in package_completion_note(window)
    assert package_completion_needs_note(replace(window, carried_casts=(HeldCast('Blade of Honor', 1, 1),)))
    assert package_completion_needs_note(replace(window, best_package_potency=6811.4))


def test_analyse_html_export_uses_same_result_once(tmp_path, monkeypatch, capsys, result):
    directory = tmp_path / "source-18"
    _write_selected_log(directory, 18)
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")
    calls = []

    def analyze(saved, action_path):
        calls.append((saved, action_path))
        return result

    monkeypatch.setattr(cli, "analyze_saved_fight", analyze)
    destination = tmp_path / "reports" / "report.html"
    assert cli.main(["analyse", str(directory), "--actions", str(actions),
                     "--html", str(destination)]) == 0
    assert calls == [(directory, actions)]
    assert "Player: Test Player" in capsys.readouterr().out
    document = destination.read_text(encoding="utf-8")
    assert "--accent:#6ee1d6" in document
    assert required_tag(BeautifulSoup(document, "html.parser"), "h1").get_text() == "Test Player"


def test_analyse_reports_html_write_errors(tmp_path, monkeypatch, capsys, result):
    directory = tmp_path / "source-18"
    _write_selected_log(directory, 18)
    actions = tmp_path / "actions.json"
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding="utf-8")
    monkeypatch.setattr(cli, "analyze_saved_fight", lambda *_: result)
    assert cli.main(["analyse", str(directory), "--actions", str(actions),
                     "--html", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize('destination,expected', [
    ('war_amt_500.html', 'reports/war_amt_500.html'),
    ('reports/war_amt_500.html', 'reports/war_amt_500.html'),
    ('exports/war_amt_500.html', 'exports/war_amt_500.html'),
])
def test_saved_log_html_bare_filename_defaults_to_reports(
    tmp_path, monkeypatch, capsys, result, destination, expected,
):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / 'source-18'
    _write_selected_log(directory, 18)
    actions = tmp_path / 'actions.json'
    actions.write_text('{"job":"machinist","patch":"7.55"}', encoding='utf-8')
    monkeypatch.setattr(cli, 'analyze_saved_fight', lambda *_: result)
    assert cli.main(['analyse', str(directory), '--actions', str(actions),
                     '--html', destination]) == 0
    assert (tmp_path / expected).is_file()
    assert not (tmp_path / 'war_amt_500.html').exists()
    assert f'Saved HTML report: {expected}' in capsys.readouterr().out


def test_war_potion_completion_marks_missing_hits_but_not_resource_casts():
    actions = tuple(BurstAction(name, 1, 0 if name in {'Infuriate', 'Primal Rend'} else 2,
                               None if name == 'Infuriate' else 1)
                    for name in ('IR spenders', 'Infuriate', 'Nascent Chaos', 'Primal Rend',
                                 'Primal Ruination', 'Primal Wrath', 'Upheaval/Orogeny', 'Onslaught'))
    with collect_report() as blocks:
        print_burst_opportunities((BurstWindow(0, 30, actions, 1000),), str, job='warrior')
    tables = [block for block in blocks if isinstance(block, ReportTable)]
    assert tables[0].rows[0][-1] == '100.0%'
    assert 'Infuriate' not in tables[1].labels
    assert all('Infuriate' not in note for _, _, note in tables[0].cell_notes)
    for block in tables:
        soup = BeautifulSoup(_table(block), 'html.parser')
        cells = soup.select('[data-state="missing-hit"]')
        assert len(cells) == 1
        assert 'Primal Rend' in cells[0]['title']


def test_war_completion_tables_highlight_shortfalls_and_unknowns():
    for labels in (('Burst', 'Start', 'IR spenders', 'Completion'),
                   ('Potion', 'Start', 'End', 'IR spenders', 'Completion')):
        prefix = ('1', '0s', '30s') if labels[0] == 'Potion' else ('1', '0s')
        soup = BeautifulSoup(_table(ReportTable(labels, ((*prefix, '2/3', '66.7%'),), (), '  ')),
                             'html.parser')
        assert len(soup.select('[data-state="shortfall"]')) == 2
        assert soup.select('[data-state="shortfall"]')[0]['title'] == '1 missed cast opportunity.'
        assert 'not a confirmed rotation loss' not in soup.get_text() + str(soup)


def test_nc_preparation_review_marks_complete_ratio_without_changing_completion():
    names = ('IR spenders', 'Infuriate', 'Nascent Chaos', 'Primal Rend',
             'Primal Ruination', 'Primal Wrath', 'Upheaval/Orogeny', 'Onslaught')
    actions = tuple(BurstAction(name, 2, 2, None if name == 'Infuriate' else 2,
                               ('Review pre-potion preparation.',) if name == 'Nascent Chaos' else (),
                               name == 'Nascent Chaos') for name in names)
    with collect_report() as blocks:
        print_burst_opportunities((BurstWindow(0, 30, actions, 1000, 1000, 1000),),
                                 str, job='warrior')
    block = next(b for b in blocks if isinstance(b, ReportTable))
    soup = BeautifulSoup(_table(block), 'html.parser')
    cells = soup.select('tbody td')
    assert cells[5].get_text() == '2/2'
    assert cells[5]['data-state'] == 'review'
    assert 'Review pre-potion preparation.' in cells[5]['title']
    assert cells[-1].get_text() == '100.0%'


def test_potion_placement_marks_zero_expected_actions_and_full_completion():
    names = ('IR spenders', 'Infuriate', 'Nascent Chaos', 'Primal Rend',
             'Primal Ruination', 'Primal Wrath', 'Upheaval/Orogeny', 'Onslaught')
    actions = tuple(BurstAction(name, 0, 0, None if name == 'Infuriate' else 0,
                               ('3 IR spenders used before this potion.',) if name == 'IR spenders' else (),
                               name == 'IR spenders') for name in names)
    window = BurstWindow(0, 30, actions, 1000, 1000, 1000,
                         ('3 IR spenders used before the potion.',))
    with collect_report() as blocks:
        print_burst_opportunities((window,), str, job='warrior')
    soup = BeautifulSoup(_table(next(b for b in blocks if isinstance(b, ReportTable))), 'html.parser')
    cells = soup.select('tbody td')
    assert cells[3].get_text() == '0/0'
    assert cells[3]['data-state'] == 'review'
    assert 'used before this potion' in cells[3]['title']
    assert cells[-1].get_text() == '100.0%'
    assert cells[-1]['data-state'] == 'review'
    assert 'not potion timing' in cells[-1]['title']


@pytest.mark.parametrize('before,after', [(True, False), (False, True), (True, True)])
def test_potion_timing_cells_mark_actions_before_start_or_after_end(before, after):
    names = ('IR spenders', 'Infuriate', 'Nascent Chaos', 'Primal Rend',
             'Primal Ruination', 'Primal Wrath', 'Upheaval/Orogeny', 'Onslaught')
    window = BurstWindow(10, 40, tuple(BurstAction(name, 0, 0, 0) for name in names), 0,
                         before_window_notes=('Fell Cleave used before this potion.',
                                              'Primal Wrath used before this potion.') if before else (),
                         after_window_notes=('Primal Ruination used after this potion.',) if after else ())
    with collect_report() as blocks:
        print_burst_opportunities((window,), str, job='warrior')
    soup = BeautifulSoup(_table(next(b for b in blocks if isinstance(b, ReportTable))), 'html.parser')
    cells = soup.select('tbody td')
    assert (cells[1].get('data-state') == 'review') is before
    assert (cells[2].get('data-state') == 'review') is after
    if before:
        before_note = cells[1]['title']
        assert isinstance(before_note, str)
        assert 'before this potion' in before_note
        assert 'Primal Wrath' in before_note
        assert before_note.count('Review potion alignment;') == 1
        assert len([line for line in before_note.splitlines() if line.startswith('- ')]) == 2
        assert '\n\nReview potion alignment;' in before_note
    if after:
        assert 'after this potion' in cells[2]['title']


@pytest.mark.parametrize('expected, wrath_expected, linked, completion', [
    (3, 1, True, '66.7%'),
    (2, 0, False, '100.0%'),
    (None, 0, False, 'n/a'),
    (3, 1, False, '66.7%'),
])
def test_earnable_wrath_counts_toward_completion_with_spender_context(
    result, expected, wrath_expected, linked, completion,
):
    note = 'Primal Wrath could be earned by completing the Inner Release spender package.'
    actions = (BurstAction('IR spenders', 2, 2, expected),
               BurstAction('Primal Rend', 1, 1, 1),
               BurstAction('Primal Ruination', 1, 1, 1),
               BurstAction('Primal Wrath', 0, 0, wrath_expected, (note,) if linked else ()))
    war = WarSummary(None, None, 0, 0, (), 0, 1, 2, 1, (), 0, (),
                     bursts=(WarBurst(307, 2, 1, 1, 0),),
                     ir_opportunities=(BurstWindow(307, 367, actions, 0),))
    soup = BeautifulSoup(render_html_report(replace(result, war=war)), 'html.parser')
    table = next(table for table in soup.select('table')
                 if [th.get_text() for th in table.select('th')][:2] == ['Burst', 'Start'])
    cells = table.select('tbody td')
    assert cells[-1].get_text() == completion
    assert (cells[5].get('data-state') == 'shortfall') == (wrath_expected == 1)
    if linked:
        assert cells[5].get_text() == '0/1'
        assert note in cells[5]['title']
        assert cells[5]['tabindex'] == '0'


def test_war_followup_context_keeps_burst_ghosts_and_leaves_combo_ghosts_in_diagnostics(result):
    from ffxiv_potency.reporting import print_war_followup_context

    result = replace(result, ghosted_times=(('Primal Rend', (10.0,)), ("Storm's Eye", (20.0,))),
                     ghosted_ending_times=(('Primal Rend', ((10.0, 'phase HP lock'),)),))
    with collect_report() as blocks:
        print_war_followup_context(result, str)
    text = '\n'.join(block.text for block in blocks if isinstance(block, ReportText))
    assert 'Primal Rend' in text and 'phase HP lock' in text
    assert "Storm's Eye" not in text


def test_war_package_tradeoff_and_followup_context_are_in_tooltips(result, capsys):
    actions = (BurstAction('IR spenders', 2, 2, 1),
               BurstAction('Primal Rend', 1, 1, 1),
               BurstAction('Primal Ruination', 0, 0, 1),
               BurstAction('Primal Wrath', 0, 0, 0))
    window = BurstWindow(10, 18, actions, 0, 1860, 2060)
    potion_actions = (actions[0], BurstAction('Infuriate', 1, 0, None),
                      BurstAction('Nascent Chaos', 1, 0, 1), *actions[1:],
                      BurstAction('Upheaval/Orogeny', 1, 1, 1),
                      BurstAction('Onslaught', 1, 1, 1))
    war = WarSummary(None, None, 0, 0, (), 0, 1, 2, 1, (), 0, (),
                     bursts=(WarBurst(10, 2, 1, 0, 0),), ir_opportunities=(window,),
                     potion_bursts=(WarPotionBurst(10, 18, (), 0, 0, 0),),
                     potion_opportunities=(replace(window, actions=potion_actions),))
    result = replace(result, war=war,
                     ghosted_times=(('Inner Chaos', (15.0,)),),
                     ghosted_targets=(('Inner Chaos', ((15.0, 'Lone Swordmaster'),)),),
                     ghosted_ending_times=(('Inner Chaos', ((15.0, 'phase HP lock'),)),),
                     follow_up_context=(
        FollowUpContext(10, ('Inner Release spenders: 2/3 casts',), 'incomplete',
                        'fight ended before sequence completed'),
        FollowUpContext(17, ('Primal Ruination',), 'missing',
                        'fight ended before sequence completed'),
    ))
    before = _encode(result)
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    assert 'Follow-up context' not in soup.get_text()
    table = next(t for t in soup.select('table')
                 if [th.get_text() for th in t.select('th')][:2] == ['Burst', 'Start'])
    cells = table.select('tbody td')
    assert cells[2]['data-state'] == 'shortfall'
    assert 'Comparison:' in cells[2]['title']
    assert 'Inner Release spenders: 2/3 casts' in cells[2]['title']
    assert cells[4]['data-state'] == 'shortfall'
    assert 'Selected package: 1 IR spenders, 1 Primal Rend, 1 Primal Ruination' in cells[6]['title']
    assert 'fight ended before sequence completed' in cells[4]['title']
    assert 'Estimated gain: 200.0' in cells[6]['title']
    potion_tables = [t for t in soup.select('table')
                     if [th.get_text() for th in t.select('th')][:1] == ['Potion']
                     and 'NC' in [th.get_text() for th in t.select('th')]]
    assert len(potion_tables) == 2
    for potion_table in potion_tables:
        headings = [th.get_text() for th in potion_table.select('th')]
        cell = potion_table.select('tbody td')[headings.index('NC')]
        assert '00m 15s Inner Chaos on Lone Swordmaster (phase HP lock)' in cell['title']
    cli._print_analysis(result)
    assert 'Follow-up context:' in capsys.readouterr().out
    assert _encode(result) == before


def test_damage_down_refresh_marks_duration_and_appears_in_its_tooltip(result, capsys):
    result = replace(result,
                     status_windows=(StatusWindow('Damage Down', 10, 45, 'expired', (15,)),),
                     damage_penalties=(DamagePenaltySummary('Damage Down', 0.85, 10, 45, 0),))
    before = _encode(result)
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    assert 'Refreshed:' not in soup.get_text()
    table = next(t for t in soup.select('table') if t.select('th')[0].get_text() == 'Effect')
    cells = table.select('tbody td')
    assert cells[0].get_text() == 'Damage Down'
    assert 'title' not in cells[0].attrs
    cell = cells[3]
    assert cell.get_text() == '35.0s'
    assert 'Refreshed: 00m 15s' in cell['title']
    assert 'included in this effect\'s duration' in cell['title']
    assert cell['data-state'] == 'info'
    assert cell['tabindex'] == '0'
    cli._print_analysis(result)
    assert 'Refreshed: 00m 15s' in capsys.readouterr().out
    assert _encode(result) == before


@pytest.mark.parametrize('job,fight,filename,anonymous', [
    ('pld', 'm12sp1', 'pld_m12sp1_7.html', False),
    ('Paladin', 'M12SP1', 'pld_m12sp1_7.html', False),
    ('war', 'umad', 'war_dmu_7.html', True),
])
def test_ranked_html_export_uses_canonical_filename_and_same_result_once(
    tmp_path, monkeypatch, capsys, result, job, fight, filename, anonymous,
):
    from ffxiv_potency.fflogs import ReportReference

    monkeypatch.chdir(tmp_path)
    directory = tmp_path / 'source-18'
    _write_selected_log(directory, 18)
    played_job = cli.SUPPORTED_JOBS[job.casefold()]
    result = replace(result, execution=ExecutionSummary(played_job, (), (), (), ()))
    reference = ReportReference('a:abc123' if anonymous else 'abc123', 9, 18)
    calls = []
    monkeypatch.setattr(cli, 'ranked_source', lambda *args, **kwargs: reference)
    monkeypatch.setattr(cli, '_resolve_analysis_directory', lambda *args, **kwargs: directory)
    monkeypatch.setattr(cli, '_verify_supported_fight', lambda _: None)
    monkeypatch.setattr(cli, '_actions_for_job', lambda *_: tmp_path / 'actions.json')

    def analyze(saved, action_path):
        calls.append((saved, action_path))
        return result

    monkeypatch.setattr(cli, 'analyze_saved_fight', analyze)
    before = _encode(result)
    assert cli.main(['fflogs', job, fight, '7', '--html']) == 0
    assert calls == [(directory, tmp_path / 'actions.json')]
    assert _encode(result) == before
    document = BeautifulSoup((tmp_path / 'reports' / filename).read_text(), 'html.parser')
    assert required_tag(document, '.eyebrow').get_text().endswith(' / Rank 7')
    assert required_tag(document, 'h1').get_text() == ('Anonymous' if anonymous else 'Test Player')
    output = capsys.readouterr().out
    assert f'Saved HTML report: reports/{filename}' in output
    assert 'Player:' in output


@pytest.mark.parametrize('arguments', [
    ['limit'], ['abc123'],
])
def test_ranked_html_requires_job_and_fight_before_api_access(arguments, capsys):
    assert cli.main(['fflogs', *arguments, '--html']) == 1
    assert 'fflogs --html requires a job and fight' in capsys.readouterr().err


def test_ranked_html_write_error_is_reported(tmp_path, monkeypatch, capsys, result):
    from ffxiv_potency.fflogs import ReportReference

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'reports').write_text('blocks directory creation')
    monkeypatch.setattr(cli, 'ranked_source', lambda *args, **kwargs: ReportReference('abc123', 9, 18))
    monkeypatch.setattr(cli, '_resolve_analysis_directory', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(cli, '_verify_supported_fight', lambda _: None)
    monkeypatch.setattr(cli, '_actions_for_job', lambda *_: tmp_path / 'actions.json')
    monkeypatch.setattr(cli, 'analyze_saved_fight', lambda *_: result)
    assert cli.main(['fflogs', 'pld', 'm12sp1', '7', '--html']) == 1
    captured = capsys.readouterr()
    assert 'error:' in captured.err
    assert 'Saved HTML report:' not in captured.out


def test_ir_completion_uses_package_potency_and_explains_the_shortfall(result):
    actions = (BurstAction('IR spenders', 2, 2, 1),
               BurstAction('Primal Rend', 1, 1, 1),
               BurstAction('Primal Ruination', 0, 0, 1),
               BurstAction('Primal Wrath', 0, 0, 0))
    war = WarSummary(None, None, 0, 0, (), 0, 1, 2, 1, (), 0, (),
                     bursts=(WarBurst(1439, 2, 1, 0, 0),),
                     ir_opportunities=(BurstWindow(1439, 1446.844, actions, 0, 1860, 2060),))
    soup = BeautifulSoup(render_html_report(replace(result, war=war)), 'html.parser')
    table = next(table for table in soup.select('table')
                 if [th.get_text() for th in table.select('th')][:2] == ['Burst', 'Start'])
    cells = table.select('tbody td')
    assert cells[-1].get_text() == '90.3%'
    assert cells[-1]['data-state'] == 'shortfall'
    assert 'Recorded / proposed potency: 1,860.0 / 2,060.0.' in cells[-1]['title']
    assert cells[2].get_text() == '2/1'
    assert cells[2].get('data-state') == 'shortfall'
    assert cells[4].get_text() == '0/1'
    assert cells[4]['data-state'] == 'shortfall'


def test_pld_potion_alignment_and_package_tradeoffs_have_explicit_states():
    from ffxiv_potency.reporting import print_job_packages

    actions = (BurstAction('Goring Blade', 1, 1, 0),
               BurstAction('Blade of Honor', 0, 0, 1),
               BurstAction('Confiteor', 0, 0, 0, ('Used before the potion.',), True))
    window = BurstWindow(10, 40, actions, 1000, 1000, 1300,
                         ('Confiteor used before the potion.',),
                         ('Confiteor used before the potion.',), ())
    with collect_report() as blocks:
        print_job_packages((('Potion', (window,)),), str, job='paladin')
    block = next(b for b in blocks if isinstance(b, ReportTable))
    soup = BeautifulSoup(_table(block), 'html.parser')
    cells = soup.select('tbody td')
    assert cells[1]['data-state'] == 'review'
    assert '- Confiteor used before the potion.' in cells[1]['title']
    assert cells[3]['data-state'] == 'shortfall'
    assert cells[4]['data-state'] == 'shortfall'
    assert 'Selected package: 1 Blade of Honor' in cells[-1]['title']
    assert 'Estimated gain: 300.0 base potency.' in cells[-1]['title']
    assert cells[5]['data-state'] == 'review'
    assert cells[-1]['data-state'] == 'shortfall'


def test_pld_full_completion_still_marks_potion_placement():
    from ffxiv_potency.reporting import print_job_packages

    window = BurstWindow(10, 40, (BurstAction('Confiteor', 0, 0, 0,
        ('Used before the potion.',), True),), 1000, 1000, 1000,
        ('Confiteor used before the potion.',))
    with collect_report() as blocks:
        print_job_packages((('Potion', (window,)),), str, job='paladin')
    block = next(b for b in blocks if isinstance(b, ReportTable))
    assert block.rows[0][-1] == '100.0%'
    assert {(r, c): state for r, c, state in block.cell_states}[0, 4] == 'review'


def test_unknown_package_retains_recorded_potion_alignment_tooltip():
    from ffxiv_potency.reporting import print_job_packages

    window = BurstWindow(10, 40, (BurstAction('Intervene', 0, 0, None),), 1000,
                         alignment_notes=('Fight or Flight started before the potion.',))
    with collect_report() as blocks:
        print_job_packages((('Potion', (window,)),), str, job='paladin')
    block = next(b for b in blocks if isinstance(b, ReportTable))
    assert block.rows[0][-1] == 'n/a'
    assert 'Fight or Flight started before the potion.' in str(block.cell_notes)


def test_completion_tooltip_distinguishes_casts_recorded_hits_and_projected_hits():
    from ffxiv_potency.analysis.burst_opportunities import ActionTiming
    from ffxiv_potency.reporting import package_completion_note

    window = BurstWindow(0, 10, (BurstAction('Confiteor', 1, 2, 1),), 1000, 1000, 1000,
        recorded_order=(('Confiteor', 1),), proposed_order=(('Confiteor', 2),),
        recorded_timings=(ActionTiming('Confiteor', 1, (1.6, 1.8)),),
        proposed_timings=(ActionTiming('Confiteor', 2, (2.7,), True),))
    note = package_completion_note(window)
    assert '00m 01.000s Confiteor | 00m 01.600s, 00m 01.800s Hit' in note
    assert '00m 02.000s Confiteor | 00m 02.700s Estimated Hit' in note
    assert 'Proposed hit times are estimates from this log.' in note


def test_pld_burst_tooltip_groups_delay_and_enhancement_by_action(result):
    original_notes = ('Blade of Valor: delayed 34.34s after burst start',
                      'Blade of Honor: delayed 58.70s after burst start',
                      'Blade of Valor: unenhanced')
    burst = PldBurst(0, 'Imperator',
        (PldFollowUp('Blade of Valor', 1, 2, 700), PldFollowUp('Blade of Honor', 1, 2, 1890)),
        original_notes)
    window = BurstWindow(0, 20, (), 0)
    context = pld_followup_context((burst,), (window,), result, str)
    notes = add_followup_tooltips({}, (window,), context)
    tooltip = notes[0, 1]
    assert tooltip.index(original_notes[0]) < tooltip.index(original_notes[2])
    assert tooltip.index(original_notes[2]) < tooltip.index(original_notes[1])
    assert burst.notes == original_notes
