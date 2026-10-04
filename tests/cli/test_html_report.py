"""HTML export, escaping, shared report content and output isolation."""

import json
from dataclasses import replace

import pytest
from bs4 import BeautifulSoup, Tag

from ffxiv_potency import cli
from ffxiv_potency.analysis.burst_opportunities import BurstAction, BurstWindow
from ffxiv_potency.analysis.cache import _encode
from ffxiv_potency.analysis.execution import ExecutionSummary
from ffxiv_potency.analysis.models import (
    ActionSummary,
    AnalysisResult,
    ConsumableIdentity,
    HitOutcomeSummary,
    PotionSummary,
    PotionWindow,
    PotionWindowTotal,
)
from ffxiv_potency.analysis.pld.follow_ups import PldFollowUpIssue
from ffxiv_potency.analysis.pld.summary import PldBurst
from ffxiv_potency.html_report import JOB_COLOURS, _table, render_html_report
from ffxiv_potency.report_document import ReportTable, ReportText, collect_report, emit_text
from ffxiv_potency.reporting import print_burst_opportunities, print_pld_followup_context

from .helpers import _write_selected_log


def required_tag(document: BeautifulSoup, selector: str) -> Tag:
    tag = document.select_one(selector)
    assert tag is not None, f"Missing HTML element: {selector}"
    return tag


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
    for table, block in zip(soup.select("table"), tables):
        assert [th.get_text() for th in table.select("thead th")] == list(block.labels)
        assert [[td.get_text() for td in row.select("td")]
                for row in table.select("tbody tr") if not row.select(".row-note")] == [
                    list(row) for row in block.rows]
    assert "Uses: 1 | Item: Grade 4 Gemdraught of Strength [HQ]" in soup.get_text()
    assert not soup.select("script[src], link[href], img[src], iframe")
    assert soup.select_one('meta[name="viewport"]')
    links = soup.select("nav a")
    headings = soup.select("main h2, main details summary")
    assert [a.get_text() for a in links] == [h.get_text() for h in headings]
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
    assert not soup.select("script, img, svg")
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


def test_metric_help_is_linked_to_keyboard_accessible_markers(result):
    soup = BeautifulSoup(render_html_report(result), 'html.parser')
    buttons = soup.select('.metric-help button')
    assert [button['aria-label'] for button in buttons] == ['About Hit Bonus', 'About Luck baseline']
    for button in buttons:
        assert button.get_text() == '(?)'
        assert button['type'] == 'button'
        tooltip_id = button['aria-describedby']
        assert isinstance(tooltip_id, str)
        tooltip = required_tag(soup, '#' + tooltip_id)
        assert tooltip['role'] == 'tooltip'
        assert 'potency' in tooltip.get_text()
        assert len(soup.select('#' + tooltip_id)) == 1
    assert 'before rate buffs' in required_tag(soup, '#help-luck-baseline').get_text()
    assert 'including guaranteed outcomes' in required_tag(soup, '#help-hit-bonus').get_text()


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
                        (("1", "00m00s", "00m20s", "0/1", "1/?", "2/2"),),
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
    assert after_table.text.startswith('  Goring =')
    context_index = blocks.index(ReportText('\n  Follow-up context:'))
    assert ReportText(f'    14s Expiacion on Kefka ({reason})') in blocks[context_index + 1:]
    assert not any(isinstance(block, ReportText) and 'Expiacion cast, no hit' in block.text for block in blocks)
    assert ReportText('    Burst 0s: Blade of Truth missing - reason unconfirmed') in blocks
    assert not any(isinstance(block, ReportText) and '200s Expiacion' in block.text for block in blocks)


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
