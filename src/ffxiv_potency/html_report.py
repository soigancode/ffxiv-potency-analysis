"""Self-contained dark HTML reports, rendered from shared presentation events."""

import json
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from .analysis.models import AnalysisResult
from .report_document import ACTION_HEADERS, ReportBlock, ReportTable, ReportText, collect_report
from .reporting import print_analysis

# FF Logs job palette, also documented at
# https://gist.github.com/stocky37/66936a6c3e82909c39f24204c7a4cb67
JOB_COLOURS = {
    "paladin": "#a8d2e6",
    "warrior": "#cf2621",
    "bard": "#91ba5e",
    "machinist": "#6ee1d6",
    "dancer": "#e2b0af",
}
JOB_ABBREVIATIONS = {"paladin": "PLD", "warrior": "WAR", "bard": "BRD",
                     "machinist": "MCH", "dancer": "DNC"}

_METRIC_HELP = {
    "Cooldown opportunities": (
        "Possible uses account for downtime and cutscenes. Cooldowns recover throughout. "
        "Self buffs can be used before bosses become targetable."
    ),
    "Luck baseline": (
        "Expected Luck from your Direct Hit and Critical Hit stats, before rate buffs. "
        "Higher-potency hits carry more weight. 100% means every eligible hit was a Direct Critical Hit."
    ),
    "Hit Bonus": (
        "Extra damage from Direct Hits and Critical Hits, including guaranteed hits. "
        "Higher-potency hits carry more weight. +48% means 48% more damage than the same attacks without DH/Crit bonuses."
    ),
    "Luck": (
        "Random Direct Hit and Critical Hit outcomes, weighted by potency. "
        "Guaranteed hits are excluded. 100% means every eligible hit was a Direct Critical Hit."
    ),
}

_CSS = """
:root{color-scheme:dark;--bg:#101113;--panel:#191b1e;--line:#303338;
 --text:#e9eaec;--muted:#aeb2b9;--accent:JOB_COLOUR;--accent-text:var(--accent);
 --accent-text:color-mix(in srgb,var(--accent) 70%,white)}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;background:var(--bg);color:var(--text);
 font:15px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:inherit}a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
.layout{max-width:1600px;margin:auto;padding:44px 32px;display:grid;
 grid-template-columns:220px minmax(0,1fr);gap:36px}
aside{position:sticky;top:30px;align-self:start}.brand{font-size:12px;letter-spacing:.14em;
 text-transform:uppercase;color:var(--accent-text);font-weight:700;margin-bottom:22px}
nav a{display:block;text-decoration:none;font-size:13px;color:var(--muted);padding:8px 0 8px 12px;
 border-left:2px solid var(--line)}nav a:hover{color:var(--text);border-color:var(--accent)}
nav a[aria-current=location]{color:var(--accent-text);border-color:var(--accent);
 background:color-mix(in srgb,var(--accent) 10%,transparent);font-weight:650}
aside>nav{max-height:calc(100vh - 100px);overflow-y:auto}
.nav-section>summary{cursor:pointer;color:var(--muted);font-size:13px}
.nav-section>summary a{display:inline-block;border:0;padding-left:6px}
.nav-section[open]>summary{color:var(--accent-text)}
.nav-section nav{padding-left:14px}.nav-section nav a{font-size:12px;padding-top:5px;padding-bottom:5px}
main{min-width:0}.hero{margin-bottom:28px;border-top:3px solid var(--accent);padding-top:24px}
.eyebrow{color:var(--accent-text);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
h1{font-size:clamp(26px,4vw,40px);letter-spacing:-.035em;line-height:1.2;margin:10px 0 16px}
.metadata{color:var(--muted);font-size:13px;margin:4px 0}.headline{font-size:16px;font-weight:600;
 margin-top:18px;padding:16px 20px;background:var(--panel);border:1px solid var(--line);border-radius:8px}
section,.assumptions{background:var(--panel);border:1px solid var(--line);border-radius:10px;
 padding:24px;margin:0 0 20px;scroll-margin-top:24px}
h2{font-size:19px;letter-spacing:-.015em;line-height:1.3;margin:0 0 18px}
h3{font-size:15px;margin:22px 0 10px;font-weight:650}p{margin:6px 0;overflow-wrap:anywhere}
.report-line{font-size:14px}.nested{margin-left:18px;color:var(--muted)}
.deep{margin-left:36px}.spacer{height:10px}.table-wrap{overflow-x:auto;margin:12px 0;
 border:1px solid var(--line);border-radius:7px;width:fit-content;max-width:100%}
table{border-collapse:collapse;width:auto;font-size:13px;font-variant-numeric:tabular-nums;
 white-space:nowrap}th,td{padding:11px 14px;text-align:center;border-bottom:1px solid var(--line)}
th{font-size:11px;color:var(--muted);letter-spacing:.03em;font-weight:650;background:#202226}
table[data-sortable] th:not(:first-child),table[data-sortable] td:not(:first-child){text-align:right}
table[data-spells] th:not(:first-child),table[data-spells] td:not(:first-child){text-align:center}
table[data-spells] th:last-child,table[data-spells] td:last-child{text-align:right}
table[data-potions] th:nth-child(-n+3),table[data-potions] td:nth-child(-n+3){text-align:center}
table[data-landed-hits] th:last-child,table[data-landed-hits] td:last-child{text-align:right}
table[data-reduced-hits] th,table[data-reduced-hits] td{text-align:center}
table[data-reduced-hits] th:last-child,table[data-reduced-hits] td:last-child{text-align:right}
table[data-ranged-chains] td:last-child{white-space:normal;text-align:left;line-height:1.9}
.chain-action{white-space:nowrap;color:var(--muted)}
.chain-ranged{color:var(--accent-text)}.chain-gap{white-space:nowrap;font-weight:700}
.chain-arrow{color:var(--muted)}
table[data-sortable] th button{font:inherit;color:inherit;background:transparent;border:0;
 padding:0;cursor:pointer;text-align:inherit}
table[data-sortable] th button:hover{color:var(--accent-text)}
table[data-sortable] th button:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
table[data-sortable] th[aria-sort=ascending] button::after{content:" ↑"}
table[data-sortable] th[aria-sort=descending] button::after{content:" ↓"}
tbody tr:last-child td{border-bottom:0}
th:first-child,td:first-child{position:sticky;left:0;z-index:1;background:var(--panel)}
th:first-child{background:#202226}
tbody tr:nth-child(even){background:#1e2023}tbody tr:hover{background:#24272b}
tbody tr:nth-child(even) td:first-child{background:#1e2023}
tr.needs-attention{background:color-mix(in srgb,var(--accent) 7%,var(--panel))}
tr.needs-attention td:first-child{box-shadow:inset 3px 0 var(--accent);
 background:color-mix(in srgb,var(--accent) 7%,var(--panel))}
tbody tr:hover td:first-child{background:#24272b}
@media screen{
 tr.table-crosshair-row>th,tr.table-crosshair-row>td,th.table-crosshair-column,td.table-crosshair-column{
 background:color-mix(in srgb,var(--accent) 12%,var(--panel))!important}
 th.table-crosshair-cell,td.table-crosshair-cell{
 background:color-mix(in srgb,var(--accent) 26%,var(--panel))!important}}
td[data-state=shortfall],td[data-state=missing-hit],td[data-state=review]{color:var(--accent-text);
 font-weight:750;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:5px}
td[data-state]{position:relative;outline-offset:-3px}
td[data-state=shortfall]::after,td[data-state=missing-hit]::after,td[data-state=review]::after{content:" !";
 font-size:11px;font-weight:800;text-decoration:none}
.floating-tooltip{position:fixed;box-sizing:border-box;width:320px;max-width:calc(100vw - 24px);
 padding:10px 12px;background:var(--bg);border:1px solid var(--accent);
 border-radius:6px;color:var(--text);font:12px/1.5 system-ui,sans-serif;text-align:left;
 white-space:normal;overflow-wrap:anywhere;z-index:1000;box-shadow:0 4px 16px #0008;pointer-events:auto;
 max-height:calc(100vh - 24px);overflow:auto}
.floating-tooltip.has-sequence{width:640px}
.floating-tooltip.has-hold{width:540px}
.floating-tooltip .hold-comparison{width:100%;margin:8px 0}
.floating-tooltip .hold-comparison th,.floating-tooltip .hold-comparison td{padding:5px 8px}
.floating-tooltip .sequence-comparison{width:100%;margin-top:8px;table-layout:fixed}
.floating-tooltip .sequence-comparison th,.floating-tooltip .sequence-comparison td{
 position:static;text-align:left;white-space:normal;vertical-align:top;padding:4px 6px;font-size:12px}
.floating-tooltip .sequence-hit{color:var(--muted)}
.floating-tooltip .sequence-comparison td.sequence-ogcd{padding-left:22px}
.floating-tooltip p{margin:0}
.floating-tooltip ul{margin:0 0 8px;padding-left:18px}
.floating-tooltip li+li{margin-top:4px}
.attention-key{font-size:12px;color:var(--muted)}
abbr[title]{cursor:help;text-decoration:underline dotted;text-underline-offset:4px}
abbr[title]:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.metric-help{display:inline-block;position:relative;margin-left:6px}
.metric-help button{font:inherit;color:var(--accent-text);background:none;border:0;
 padding:0;cursor:help}.metric-help button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.metric-tooltip{display:none;position:absolute;left:0;bottom:calc(100% + 8px);
 width:320px;max-width:calc(100vw - 48px);padding:12px 14px;border:1px solid var(--accent);
 border-radius:7px;background:var(--bg);color:var(--text);font-size:13px;font-weight:400;
 line-height:1.5;z-index:4;box-shadow:0 4px 16px #0008}
.metric-help:hover .metric-tooltip,.metric-help:focus-within .metric-tooltip{display:block}
td[data-state=info]{color:var(--accent-text);text-decoration:underline dotted;
text-underline-offset:3px;cursor:help}
table[data-cooldown-timing] td[data-state=info]{color:inherit}
td[data-state=unknown]{color:var(--muted)}.row-note{font-size:12px;color:var(--muted);white-space:normal}
.execution .report-line{padding-left:12px;border-left:2px solid var(--accent);margin:10px 0}
.assumptions summary{cursor:pointer;font-size:19px;font-weight:650}
.assumptions[open] summary{margin-bottom:18px}.assumptions .report-line{color:var(--muted);font-size:13px}
footer{color:var(--muted);font-size:12px;padding:8px 0 24px}
@media(max-width:1000px){.layout{grid-template-columns:1fr;padding:24px 16px;gap:20px}
 aside{position:static}nav{display:flex;flex-wrap:wrap;gap:6px 14px}nav a{border-left:0;
 padding:3px 0;font-size:12px}.brand{margin-bottom:10px}section,.assumptions{padding:18px}
 .report-line{position:relative}.metric-help{position:static}
 .metric-tooltip{left:0;width:100%;max-width:320px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{:root{color-scheme:light;--bg:white;--panel:white;--text:#111;--muted:#444;--line:#ccc}
 .layout{display:block;padding:0}aside,.metric-help,.floating-tooltip{display:none}section,.assumptions{border:0;padding:8px 0;
 margin:12px 0}.table-wrap{overflow:visible}th{background:#eee}th,td{padding:5px 8px;
 white-space:normal}h2,h3{break-after:avoid}tr{break-inside:avoid}details:not([open])>*:not(summary){display:block}}
"""


_TABLE_HOVER_SCRIPT = """
(() => {
  for (const table of document.querySelectorAll('main table[data-crosshair]')) {
    let active = null;
    let highlighted = [];
    function clear() {
      for (const cell of highlighted) cell.classList.remove('table-crosshair-column');
      active?.parentElement.classList.remove('table-crosshair-row');
      active?.classList.remove('table-crosshair-cell');
      active = null;
      highlighted = [];
    }
    table.addEventListener('pointerover', event => {
      const cell = event.target.closest('th,td');
      if (!cell || cell.closest('table') !== table || cell === active) return;
      clear();
      if (cell.colSpan !== 1) return;
      active = cell;
      cell.parentElement.classList.add('table-crosshair-row');
      cell.classList.add('table-crosshair-cell');
      const column = [...cell.parentElement.cells].slice(0, cell.cellIndex)
        .reduce((total, item) => total + item.colSpan, 0);
      for (const row of table.rows) {
        let offset = 0;
        for (const item of row.cells) {
          if (offset === column && item.colSpan === 1) {
            item.classList.add('table-crosshair-column');
            highlighted.push(item);
          }
          offset += item.colSpan;
        }
      }
    });
    table.addEventListener('pointerleave', clear);
    table.addEventListener('pointercancel', clear);
  }
})();
"""


_SECTION_NAV_SCRIPT = """
(() => {
  const sections = [...document.querySelectorAll('main section[id], main details.assumptions[id]')];
  const links = [...document.querySelectorAll('aside a[href^="#"]')];
  const reports = [...document.querySelectorAll('details.player-report')];
  const menus = [...document.querySelectorAll('aside details.nav-section')];
  function updateSection() {
    const report = reports.find(item => {
      const bounds = item.getBoundingClientRect();
      return item.open && bounds.top <= 160 && bounds.bottom > 160;
    });
    const visible = sections.filter(section => section.getClientRects().length
      && (!report || section.closest('details.player-report') === report));
    const current = visible.filter(section => section.getBoundingClientRect().top <= 160).pop()
      || visible[0];
    for (const menu of menus) {
      const expanded = menu.dataset.section === current?.id;
      if (menu.open !== expanded) menu.open = expanded;
    }
    const subsections = current ? [...current.querySelectorAll('h3[id]')]
      .filter(heading => heading.getClientRects().length
        && heading.getBoundingClientRect().top <= 160) : [];
    const location = subsections.at(-1) || current;
    for (const link of links) {
      if (location && link.hash === '#' + location.id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
  }
  let pending = false;
  function scheduleUpdate() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; updateSection(); });
  }
  window.addEventListener('scroll', scheduleUpdate, {passive: true});
  window.addEventListener('resize', scheduleUpdate);
  window.addEventListener('hashchange', scheduleUpdate);
  document.addEventListener('toggle', scheduleUpdate, true);
  updateSection();
})();
"""


_TOOLTIP_SCRIPT = """
(() => {
  const tooltip = document.getElementById('action-tooltip');
  let active = null;
  let hideTimer = null;
  function hide() {
    clearTimeout(hideTimer);
    tooltip.hidden = true;
    if (active) active.removeAttribute('aria-describedby');
    active = null;
  }
  function show(element) {
    hide();
    active = element;
    tooltip.replaceChildren();
    let list = null;
    let holdBody = null;
    const sequences = [[], []];
    let sequence = -1;
    for (const line of element.dataset.tooltip.split('\\n')) {
      if (line.startsWith('Action | Inside FoF | ')) {
        const table = document.createElement('table');
        table.className = 'hold-comparison';
        const head = document.createElement('thead');
        const row = document.createElement('tr');
        for (const label of line.split(' | ')) {
          const cell = document.createElement('th');
          cell.scope = 'col';
          cell.textContent = label;
          row.appendChild(cell);
        }
        head.appendChild(row);
        holdBody = document.createElement('tbody');
        table.append(head, holdBody);
        tooltip.appendChild(table);
        continue;
      }
      if (holdBody && line.includes(' | ')) {
        const row = document.createElement('tr');
        for (const value of line.split(' | ')) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        }
        holdBody.appendChild(row);
        continue;
      }
      holdBody = null;
      if (line === 'Recorded order:' || line === 'Proposed order:') {
        sequence = line === 'Recorded order:' ? 0 : 1;
        continue;
      }
      if (sequence >= 0 && line.startsWith('- ')) {
        sequences[sequence].push(line.slice(2));
        continue;
      }
      if (line.startsWith('- ')) {
        if (!list) {
          list = document.createElement('ul');
          tooltip.appendChild(list);
        }
        const item = document.createElement('li');
        item.textContent = line.slice(2);
        list.appendChild(item);
      } else if (line.trim()) {
        const paragraph = document.createElement('p');
        paragraph.textContent = line;
        tooltip.appendChild(paragraph);
        list = null;
      }
    }
    const hasSequence = sequences.some(items => items.length);
    tooltip.classList.toggle('has-sequence', hasSequence);
    tooltip.classList.toggle('has-hold', !!tooltip.querySelector('.hold-comparison'));
    if (hasSequence) {
      const table = document.createElement('table');
      table.className = 'sequence-comparison';
      const head = document.createElement('thead');
      const header = document.createElement('tr');
      for (const label of ['Recorded order', 'Proposed order']) {
        const cell = document.createElement('th');
        cell.scope = 'col';
        cell.textContent = label;
        header.appendChild(cell);
      }
      head.appendChild(header);
      table.appendChild(head);
      const body = document.createElement('tbody');
      for (let index = 0; index < Math.max(...sequences.map(items => items.length)); index++) {
        const row = document.createElement('tr');
        for (const items of sequences) {
          const cell = document.createElement('td');
          const entry = items[index] || '-';
          if (entry.startsWith('  ')) cell.className = 'sequence-ogcd';
          const parts = entry.trimStart().split(' | ');
          for (const [partIndex, text] of parts.entries()) {
            const line = document.createElement('div');
            line.textContent = text;
            if (partIndex) line.className = 'sequence-hit';
            cell.appendChild(line);
          }
          row.appendChild(cell);
        }
        body.appendChild(row);
      }
      table.appendChild(body);
      tooltip.appendChild(table);
    }
    tooltip.hidden = false;
    element.setAttribute('aria-describedby', tooltip.id);
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;
    tooltip.style.maxWidth = `${Math.max(0, viewportWidth - 24)}px`;
    tooltip.style.maxHeight = `${Math.max(0, viewportHeight - 24)}px`;
    const bounds = element.getBoundingClientRect();
    const size = tooltip.getBoundingClientRect();
    const left = Math.max(12, Math.min(bounds.left, viewportWidth - size.width - 12));
    const above = bounds.top - size.height - 8;
    const top = above >= 12 ? above : Math.max(12,
      Math.min(bounds.bottom + 8, viewportHeight - size.height - 12));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }
  document.querySelectorAll('td[data-state][title], th abbr[data-help][title]').forEach(element => {
    element.dataset.tooltip = element.getAttribute('title');
    element.removeAttribute('title');
    element.addEventListener('mouseenter', () => show(element));
    element.addEventListener('mouseleave', () => {
      if (active === element && document.activeElement !== element) {
        hideTimer = setTimeout(hide, 160);
      }
    });
    element.addEventListener('focus', () => show(element));
    element.addEventListener('blur', () => { if (active === element) hide(); });
  });
  tooltip.addEventListener('mouseenter', () => clearTimeout(hideTimer));
  tooltip.addEventListener('mouseleave', () => {
    if (document.activeElement !== active) hide();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
  document.addEventListener('scroll', event => {
    if (!tooltip.contains(event.target)) hide();
  }, true);
  window.addEventListener('resize', hide);
})();
"""


def _action_name(label: str, full_name: str, *, floating: bool = False) -> str:
    name = escape(full_name, quote=True)
    return (f'<abbr title="{name}" tabindex="0" aria-label="{name}"'
            + (' data-help' if floating else '') + '>'
            + escape(label) + ('<span class="header-help-cue" aria-hidden="true"> (?)</span>'
                               if floating else '') + '</abbr>')


def _numeric_table_value(value: str) -> float | None:
    numbers = [float(n.replace(',', '')) for n in re.findall(r'(?<![\d.,])[-+]?\d[\d,]*(?:\.\d+)?', value)]
    return sum(numbers) / len(numbers) if numbers else None


def _ability_names(job, since):
    if not job or not since:
        return frozenset()
    from .datasets import load_manifest, select_set

    manifest, root = load_manifest(job)
    snapshot = select_set(manifest, 'action_sets', since)
    actions = json.loads((root / snapshot['file']).read_text(encoding='utf-8'))['actions']
    return frozenset(a['name'] for a in actions if a.get('type', '').casefold() == 'ability')


def _indent_sequence_abilities(note, ability_names):
    lines = []
    sequence = False
    for line in note.split('\n'):
        if line in {'Recorded order:', 'Proposed order:'}:
            sequence = True
        if sequence and line.startswith('- '):
            action = re.fullmatch(r'- (?:cast )?-?\d+m \d+(?:\.\d+)?s (.+)',
                                  line.split(' | ', 1)[0])
            action_name = re.sub(r' (?:\(Held\)|\(Hold\)|\(from the previous window\))$', '',
                                 action[1]) if action else ''
            if action and all(name in ability_names for name in action_name.split('/')):
                line = '-   ' + line[2:]
        lines.append(line)
    return '\n'.join(lines)


def _table(block: ReportTable, *, show_attention_key: bool = True, crosshair: bool = False,
           ability_names=frozenset()) -> str:
    timing = block.labels == ('Action', 'Ready while usable', 'Longest delay')
    spells = block.labels == ('Spell', 'Enhancement', 'Cast evidence', 'Casts')
    ranged_chains = block.labels == ('Time', 'GCD sequence')
    potions = block.labels == ('Potion', 'Start', 'End', 'Base potency', 'Potion gain')
    landed_hits = block.labels[0] in {'Burst', 'Potion'} and block.labels[-1] == 'Landed potency'
    reduced_hits = block.labels == ('Time', 'Action', 'Target', 'Damage retained')
    metrics = block.labels == ('Metric', 'Baseline', 'Recorded', 'Adjusted')
    outcomes = block.labels == ('Outcome', 'Gear baseline', 'Observed', 'Difference', 'Hits')
    hit_statistics = metrics or outcomes
    action_totals = (block.labels[0] in {'Action', 'Pet action'}
                     and block.labels[1:] == ('Uses', 'Hits/ticks', 'Landed potency'))
    auto_attacks = block.labels == ('Action', 'Hits', 'Weapon delay', 'Base potency per hit', 'Landed potency')
    sortable = action_totals or timing or spells or potions or reduced_hits or hit_statistics
    sort_columns = (set(range(len(block.labels))) if hit_statistics else {0, 3}
                    if spells or reduced_hits else {0, 3, 4} if potions
                    else set(range(1, len(block.labels))))
    headings = []
    for column, label in enumerate(block.labels):
        name = escape(label)
        if label in ACTION_HEADERS:
            name = _action_name(label, ACTION_HEADERS[label])
        if potions and label == 'Base potency':
            name = _action_name(label, 'Landed damage with a potion snapshot, including DoT ticks and auto-attacks. Base potency excludes the potion bonus.')
        if metrics and label == 'Adjusted':
            name = _action_name(label, "Removes the expected benefit of other players' Direct Hit and Critical Hit rate buffs.")
        if metrics and label == 'Baseline':
            name = _action_name(label, _METRIC_HELP['Luck baseline'])
        if metrics and label == 'Recorded':
            name = _action_name(label, 'Recorded values include other players\' rate buffs. Reconstructed DoT ticks without DH or Crit outcomes are excluded from Hit Bonus and Luck.')
        if outcomes:
            descriptions = {
                'Outcome': 'Guaranteed Direct Hits and Critical Hits are excluded from this table and Luck, but count toward Hit Bonus. Reconstructed DoT ticks without recorded outcomes are also excluded.',
                'Gear baseline': 'Expected frequency from your Direct Hit and Critical Hit stats, before rate buffs.',
                'Observed': 'Share of eligible recorded hits with this outcome.',
                'Difference': 'Observed frequency minus the gear baseline, in percentage points.',
            }
            if label in descriptions:
                name = _action_name(label, descriptions[label])
        if sortable and column in sort_columns:
            direction = ('descending' if timing and column == 1 or action_totals and column == 3 else
                         'ascending' if (spells or potions or reduced_hits or hit_statistics) and column == 0 else 'none')
            headings.append(f'<th scope="col" aria-sort="{direction}"><button type="button"'
                            f' data-sort-column="{column}">{name}</button></th>')
        else:
            headings.append(f'<th scope="col">{name}</th>')
    header = "".join(headings)
    rows = []
    cell_notes = {(row, col): note for row, col, note in block.cell_notes}
    cell_states = {(row, col): state for row, col, state in block.cell_states}
    flagged = False
    burst = (block.labels[:3] == ("Burst", "Buff start", "Buff end") and "Imperator" in block.labels
             or block.labels[:3] == ("Potion", "Start", "End") and "Completion" in block.labels
             or block.labels[:2] == ("Burst", "Start") and "Completion" in block.labels)
    ordered_rows = list(enumerate(block.rows))
    spell_order = {name: i for i, name in enumerate(dict.fromkeys(row[0] for row in block.rows))} if spells else {}
    if timing:
        ordered_rows.sort(key=lambda entry: (
            _numeric_table_value(entry[1][1]) is None,
            -(_numeric_table_value(entry[1][1]) or 0)))
    if action_totals:
        ordered_rows.sort(key=lambda entry: (
            _numeric_table_value(entry[1][3]) is None,
            -(_numeric_table_value(entry[1][3]) or 0)))
    for i, row in ordered_rows:
        cells = []
        row_flagged = False
        for col, value in enumerate(row):
            state = ""
            reason = ""
            ratio = re.fullmatch(r"(\d+)/(\d+|\?)", value) if burst else None
            if ratio:
                actual, expected = ratio.groups()
                if expected == "?":
                    state, reason = "unknown", "Expectation unconfirmed"
                elif int(actual) < int(expected):
                    missed = int(expected) - int(actual)
                    state = "shortfall"
                    reason = f"{missed} missed cast " + ("opportunity." if missed == 1 else "opportunities.")
            if burst and block.labels[col] == "Completion":
                if value == "n/a":
                    state, reason = "unknown", "Incomplete expectations or no conservative opportunities"
                elif float(value.rstrip("%")) < 100:
                    state = "shortfall"
            if (i, col) in cell_notes:
                state = cell_states.get((i, col), "missing-hit")
                if block.labels[col] == "Completion" and state == "review":
                    reason = "Review this comparison."
                reason = (reason + " " + cell_notes[i, col]).strip()
            attributes = ""
            if sortable and col in sort_columns:
                number = spell_order[value] if spells and col == 0 else _numeric_table_value(value)
                if hit_statistics and col == 0:
                    number = i
                if reduced_hits and col == 0:
                    timestamp = re.fullmatch(r'(-?)(\d+)m (\d+)s', value)
                    number = ((int(timestamp[2]) * 60 + int(timestamp[3]))
                              * (-1 if timestamp[1] else 1)) if timestamp else None
                if number is not None:
                    attributes += f' data-sort-value="{number}"'
            if state:
                reason = _indent_sequence_abilities(reason, ability_names)
                attributes += (f' data-state="{state}" tabindex="0" title="{escape(reason, quote=True)}"'
                              f' aria-label="{escape(block.labels[col] + ": " + value + ". " + reason, quote=True)}"')
            if state in {"shortfall", "missing-hit", "review"}:
                row_flagged = flagged = True
            content = escape(value)
            if metrics and col == 0 and value in _METRIC_HELP:
                content = _action_name(value, _METRIC_HELP[value])
            if ranged_chains and col == 1:
                parts = []
                for part in value.split(' -> '):
                    if re.fullmatch(r'\d+\.\d+s', part):
                        parts.append('<strong class="chain-gap">' + escape(part) + '</strong>')
                    else:
                        css = 'chain-action' + (' chain-ranged' if part in {'HS (hard-cast)', 'SL'} else '')
                        action = re.sub(r'\b(HS|SL)\b', lambda match: _action_name(
                            match[0], {'HS': 'Holy Spirit', 'SL': 'Shield Lob'}[match[0]]), escape(part))
                        parts.append(f'<span class="{css}">{action}</span>')
                content = ' <span class="chain-arrow">&rarr;</span> '.join(parts)
            cells.append(f"<td{attributes}>{content}</td>")
        row_attributes = f' data-original-order="{i}"' if sortable else ''
        if row_flagged:
            row_attributes += ' class="needs-attention"'
        rows.append('<tr' + row_attributes + '>' + "".join(cells) + "</tr>")
        if i < len(block.notes) and block.notes[i]:
            rows.append(f'<tr><td class="row-note" colspan="{len(block.labels)}">'
                        + escape(block.notes[i]).replace("\n", "<br>") + "</td></tr>")
    return ('<div class="table-wrap" tabindex="0" role="region" aria-label="'
            + escape(", ".join(block.labels), quote=True) + '"><table'
            + (' data-sortable' if sortable else '')
            + (' data-cooldown-timing' if timing else '')
            + (' data-spells' if spells else '')
            + (' data-potions' if potions else '')
            + (' data-landed-hits' if landed_hits else '')
            + (' data-auto-attacks' if auto_attacks else '')
            + (' data-reduced-hits' if reduced_hits else '')
            + (' data-ranged-chains' if ranged_chains else '')
            + (' data-crosshair' if crosshair else '') + '><thead><tr>'
            + header + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            + ('<p class="attention-key">! = Potential potency loss, missing hit or alignment to review. '
               'Hover or focus for details.</p>'
               if flagged and show_attention_key else ""))


def _line(line: str, *, action_names: bool = False, anchor_prefix: str = '',
          notes: tuple[tuple[str, str], ...] = ()) -> str:
    if not line.strip():
        return '<div class="spacer" aria-hidden="true"></div>'
    text = line.strip()
    indent = len(line) - len(line.lstrip())
    css = "report-line" + (" nested deep" if indent >= 6 else " nested" if indent >= 4 else "")
    label = text.split(":", 1)[0]
    help_marker = ""
    if label in _METRIC_HELP:
        help_id = anchor_prefix + "help-" + label.lower().replace(" ", "-")
        help_marker = (f'<span class="metric-help"><button type="button" aria-label="About {label}" '
                       f'aria-describedby="{help_id}">(?)</button>'
                       f'<span class="metric-tooltip" role="tooltip" id="{help_id}">'
                       + escape(_METRIC_HELP[label]) + "</span></span>")
    if text.endswith(":"):
        return f"<h3>{escape(text[:-1])}{help_marker}</h3>"
    content = escape(text)
    pre_pull = re.fullmatch(r"(.+: )(\d+(?:/\d+)? uses?) \(including pre-pull\)", text)
    if pre_pull:
        content = (escape(pre_pull[1])
                   + '<abbr title="Includes pre-pull uses." tabindex="0">'
                   + escape(pre_pull[2]) + '</abbr>')
    if action_names:
        names = {"HS": "Holy Spirit", "SL": "Shield Lob", "T": "Tomahawk"}
        content = re.sub(r"\b(HS|SL|T)\b", lambda match: _action_name(
            match[0], names[match[0]]), content)
    for value, note in notes:
        content = content.replace(escape(value),
                                  '<abbr tabindex="0" title="' + escape(note, quote=True)
                                  + '">' + escape(value) + '</abbr>', 1)
    return f'<p class="{css}">{content}{help_marker}</p>'


def _saved_rank(directory: Path | None, result: AnalysisResult, job: str) -> str | None:
    """Read an unambiguous individual ranking without fetching live standings."""
    if directory is None:
        return None
    try:
        rankings = json.loads((directory / "rankings.json").read_text(encoding="utf-8"))
        fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
        master = json.loads((directory / "master-data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not all(isinstance(value, dict) for value in (rankings, fight, master)):
        return None
    actors = master.get("actors", [])
    if not isinstance(actors, list):
        return None
    source_match = re.fullmatch(r"source-(\d+)", directory.name)
    selected = [actor for actor in actors if isinstance(actor, dict) and (
        actor.get("id") == int(source_match[1]) if source_match else
        str(actor.get("name", "")).casefold() == result.source_name.casefold()
        and str(actor.get("subType", "")).casefold() == job
    )]
    if len(selected) != 1 or fight.get("id") is None:
        return None
    server = selected[0].get("server")
    metric = rankings.get("metric")
    candidates = ["rdps", "dps"]
    if isinstance(metric, str) and metric in {"ndps", "rdps", "dps"}:
        candidates.append("rankings")
    for key in candidates:
        document = rankings.get(key)
        data = document.get("data", []) if isinstance(document, dict) else []
        if not isinstance(data, list):
            continue
        matches = []
        for entry in data:
            if not isinstance(entry, dict) or entry.get("fightID") != fight["id"]:
                continue
            roles = entry.get("roles", {})
            for role in roles.values() if isinstance(roles, dict) else ():
                characters = role.get("characters", []) if isinstance(role, dict) else []
                for character in characters if isinstance(characters, list) else ():
                    if not isinstance(character, dict) or "id_2" in character:
                        continue
                    if (str(character.get("name", "")).casefold() != result.source_name.casefold()
                            or str(character.get("class", "")).casefold() != job):
                        continue
                    recorded_server = character.get("server")
                    if server and (not isinstance(recorded_server, dict)
                                   or recorded_server.get("name") != server):
                        continue
                    value = character.get("rank")
                    if not isinstance(value, bool) and isinstance(value, (int, str)) and re.fullmatch(
                        r"~?[1-9][0-9]*", str(value)
                    ):
                        matches.append(str(value))
        if len(matches) == 1:
            return f"Saved rank {matches[0]}"
        if len(matches) > 1:
            return None
    return None


def _render_analysis_report(result: AnalysisResult, *, directory: Path | None = None,
                            anonymous: bool = False, rank: int | None = None,
                            anchor_prefix: str = '', embedded: bool = False,
                            section_navigation: list[str] | None = None) -> str:
    """Render existing results without changing calculations or cached models."""
    from .cli import CURRENT_FIGHTS, _display_player_name, _source_job

    job = result.execution.job if result.execution else (_source_job(directory) if directory else "")
    if not job and result.pld:
        job = "paladin"
    ability_names = _ability_names(job, result.actions_since)
    colour = JOB_COLOURS.get(job, "#a8d2e6")
    player = re.sub(r"\x1b\[[0-9;]*m", "", _display_player_name(result.source_name, anonymous=anonymous))
    rank_label = f"Rank {rank}" if rank is not None else _saved_rank(directory, result, job)
    fight_label = next((alias.upper() for alias, encounter in CURRENT_FIGHTS.items()
                        if encounter == result.encounter_id), result.fight_name)
    with collect_report() as blocks:
        print_analysis(result, directory=directory, anonymous=anonymous, rank=rank, tooltip_context=True)

    intro: list[ReportBlock] = []
    sections: list[tuple[str, list[ReportBlock]]] = []
    current = intro
    for block in blocks:
        if isinstance(block, ReportTable):
            current.append(block)
            continue
        for line in block.text.split("\n"):
            if line and not line.startswith(" ") and line.endswith(":"):
                current = []
                sections.append((line[:-1], current))
            else:
                current.append(ReportText(line, block.notes))

    navigation = []
    content = []
    for i, (heading, section_blocks) in enumerate(sections, 1):
        anchor = f"{anchor_prefix}section-{i}"
        heading_id = f"{anchor_prefix}heading-{i}"
        subsections = []
        rendered = []
        attention_explained = False
        subsection_heading = ''
        for block in section_blocks:
            if isinstance(block, ReportTable):
                table = _table(block, show_attention_key=not attention_explained,
                               crosshair=subsection_heading in {'Burst completion', 'Landed hits and potency'},
                               ability_names=ability_names)
                attention_explained |= '<p class="attention-key">' in table
                rendered.append(table)
            else:
                line = _line(block.text, action_names=heading == "Melee downtime",
                             anchor_prefix=anchor_prefix, notes=block.notes)
                if line.startswith('<h3>'):
                    # Console blank lines duplicate the heading's CSS spacing.
                    while rendered and rendered[-1] == '<div class="spacer" aria-hidden="true"></div>':
                        rendered.pop()
                    subsection_heading = block.text.strip()[:-1]
                if line.startswith('<h3>') and heading == 'Cooldowns and burst windows':
                    subsection = f'{anchor}-subsection-{len(subsections) + 1}'
                    subsections.append(f'<a href="#{subsection}">{escape(block.text.strip()[:-1])}</a>')
                    line = line.replace('<h3>', f'<h3 id="{subsection}">', 1)
                if rendered or block.text.strip():
                    rendered.append(line)
        section_link = f'<a href="#{anchor}">{escape(heading)}</a>'
        if subsections:
            navigation.append(f'<details class="nav-section" data-section="{anchor}">'
                              f'<summary>{section_link}</summary><nav aria-label="'
                              + escape(heading + ' subsections', quote=True) + '">'
                              + ''.join(subsections) + '</nav></details>')
        else:
            navigation.append(section_link)
        while rendered and rendered[-1] == '<div class="spacer" aria-hidden="true"></div>':
            rendered.pop()
        body = "".join(rendered)
        if heading == "Data and assumptions":
            content.append(f'<details class="assumptions" id="{anchor}">'
                           f"<summary>{escape(heading)}</summary>{body}</details>")
        else:
            css = ' class="execution"' if heading == "Execution summary" else ""
            content.append(f'<section id="{anchor}"{css} aria-labelledby="{heading_id}">'
                           f'<h2 id="{heading_id}">{escape(heading)}</h2>{body}</section>')
    metadata = []
    for block in intro:
        if isinstance(block, ReportText) and block.text.strip():
            if block.text.startswith("Player:"):
                continue
            css = "headline" if block.text.startswith("Landed potency:") else "metadata"
            metadata.append(f'<p class="{css}">{escape(block.text.strip())}</p>')
    job_label = JOB_ABBREVIATIONS.get(job, "Analysis")
    hero = ('<header class="hero"><div class="eyebrow">' + escape(job_label)
            + (" / " + escape(rank_label) if rank_label else "") + "</div><h1>" + escape(player)
            + "</h1>" + "".join(metadata) + "</header>")
    if embedded:
        if section_navigation is not None:
            section_navigation.extend(navigation)
        return hero + ''.join(content)
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(player)} - {escape(fight_label)} | FFXIV Potency Analysis</title>"
            + "<style>" + _CSS.replace("JOB_COLOUR", colour) + "</style></head><body>"
            + '<div class="layout"><aside><div class="brand">FFXIV potency analysis</div>'
            + '<nav aria-label="Report sections">' + "".join(navigation) + "</nav></aside><main>"
            + hero + "".join(content)
            + "<footer>FFXIV potency analysis / Counts and diagnostics follow the recorded evidence.</footer>"
            + '</main></div><div id="action-tooltip" class="floating-tooltip" role="tooltip" hidden></div>'
            + '<script>' + _TOOLTIP_SCRIPT + _SECTION_NAV_SCRIPT + _TABLE_HOVER_SCRIPT + _TABLE_SORT_SCRIPT
            + '</script></body></html>\n')


def render_html_report(result: AnalysisResult, *, directory: Path | None = None,
                       anonymous: bool = False, rank: int | None = None) -> str:
    return _render_analysis_report(result, directory=directory, anonymous=anonymous, rank=rank)


def _leaderboard_sort_values(result: AnalysisResult, baseline: AnalysisResult,
                             directory: Path) -> dict[str, float | int | None]:
    """Use numeric results, including range midpoints, rather than formatted cells."""
    from .cli import _fight_date

    try:
        date = datetime.strptime(_fight_date(directory, full_year=True), '%d/%m/%Y').replace(tzinfo=UTC).toordinal()
    except ValueError:
        date = None
    delta = None
    if baseline.pps_min > 0 and baseline.pps_max > 0:
        delta = 50 * (result.pps_min / baseline.pps_max + result.pps_max / baseline.pps_min - 2)
    if result is baseline:
        delta = 0
    return {'Duration': result.duration_seconds, 'Targetable': result.targetable_seconds,
            'rDPS/nDPS': result.rdps if result.rdps is not None else result.ndps,
            'rDPS': result.rdps, 'nDPS': result.ndps, 'DPS': result.dps,
            'Potency': (result.potency_min + result.potency_max) / 2,
            'PPS': (result.pps_min + result.pps_max) / 2, 'dPPS': delta,
            'aHB': result.adjusted_hit_bonus, 'aLuck': result.adjusted_luck_score,
            'HB': result.hit_bonus, 'Luck': result.luck_score, 'Date': date}


_TABLE_SORT_SCRIPT = """
(() => {
 for (const table of document.querySelectorAll('#leaderboard table, table[data-sortable]')) {
  const body = table.tBodies[0];
  for (const button of table.querySelectorAll('button[data-sort-column]')) {
    button.addEventListener('click', () => {
      const header = button.closest('th');
      const ascending = header.getAttribute('aria-sort') !== 'ascending';
      for (const other of table.querySelectorAll('th[aria-sort]')) other.setAttribute('aria-sort', 'none');
      header.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
      const column = Number(button.dataset.sortColumn);
      const rows = [...body.rows];
      rows.sort((left, right) => {
        const a = left.cells[column].dataset.sortValue;
        const b = right.cells[column].dataset.sortValue;
        const original = Number(left.dataset.originalOrder) - Number(right.dataset.originalOrder);
        if (a === undefined && b === undefined) return original;
        if (a === undefined) return 1;
        if (b === undefined) return -1;
        const difference = Number(a) - Number(b);
        return difference ? difference * (ascending ? 1 : -1) : original;
      });
      for (const row of rows) body.appendChild(row);
    });
  }
 }
})();
"""


def write_leaderboard_report(results: list[AnalysisResult], directories: list[Path],
                             ranks: list[int], labels: tuple[str, ...],
                             rows: list[tuple[str, ...]], output: Path, *,
                             job: str, skipped: tuple[tuple[int, str], ...] = (),
                             notes: tuple[str, ...] = (), metadata: tuple[str, ...] = (),
                             ranked: bool = True) -> None:
    """Save the comparison and complete analyses together without recalculating."""
    from .cli import (
        CURRENT_FIGHTS,
        ENCOUNTER_NAMES,
        _display_player_name,
        _format_pps,
        _reference_from_directory,
    )

    if not results or not (len(results) == len(directories) == len(ranks) == len(rows)):
        raise ValueError('leaderboard reports require matching results, directories, ranks and rows')
    fight = next((alias.upper() for alias, encounter in CURRENT_FIGHTS.items()
                  if encounter == results[0].encounter_id), results[0].fight_name)
    report_label = 'Leaderboard' if ranked else 'Comparison'
    navigation = [f'<a class="leaderboard-link" href="#leaderboard">{report_label}</a>']
    table_rows = []
    reports = []
    baseline = results[min(range(len(ranks)), key=lambda index: ranks[index])]
    sort_values: dict[str, float | int | None] = {}
    for index, (result, directory, rank, row) in enumerate(zip(results, directories, ranks, rows), 1):
        reference = _reference_from_directory(directory)
        anonymous = reference is not None and reference.report_code.startswith('a:')
        player = _display_player_name(result.source_name, anonymous=anonymous)
        player = re.sub(r'\x1b\[[0-9;]*m', '', player)
        anchor = f'player-{index}'
        name = f'Rank {rank} - {player}' if ranked else player
        sections = []
        analysis = _render_analysis_report(result, directory=directory, rank=rank if ranked else None,
                                           anonymous=anonymous, anchor_prefix=anchor + '-',
                                           embedded=True, section_navigation=sections)
        navigation.append(f'<details class="sidebar-player" data-player="{anchor}"'
                          + (' open' if index == 1 else '') + '><summary>'
                          + f'<a href="#{anchor}">{escape(name)}</a></summary>'
                          + '<nav aria-label="' + escape(name + ' sections', quote=True) + '">'
                          + ''.join(sections) + '</nav></details>')
        sort_values = _leaderboard_sort_values(result, baseline, directory)
        cells = []
        for label, value in zip(labels, row):
            key = sort_values.get(label)
            attribute = f' data-sort-value="{key}"' if key is not None else ''
            cells.append('<td' + attribute + '>' + escape(value) + '</td>')
        table_rows.append(f'<tr data-original-order="{index}"><td data-sort-value="{rank}">'
                          + str(rank) + '</td><td><a href="#' + anchor + '">'
                          + escape(player) + '</a></td>'
                          + ''.join(cells) + '</tr>')
        reports.append(f'<details class="player-report" id="{anchor}"'
                       + (' open' if index == 1 else '') + '><summary>' + escape(name)
                       + f' | PPS: {_format_pps(result.pps_min, result.pps_max)}'
                       + '</summary><div class="player-body">'
                       + analysis + '</div></details>')
    table_rows = [row for _, row in sorted(zip(ranks, table_rows), key=lambda item: item[0])]
    help_labels = {'dPPS': ('PPS difference from the lowest selected FF Logs rank' if ranked
                            else 'PPS difference from the first selected player'),
                   'aHB': 'Adjusted Hit Bonus', 'aLuck': 'Adjusted Luck',
                   'HB': 'Hit Bonus', 'PPS': 'Potency per Second (Targetable)'}
    note_items = []
    for note in notes:
        if note.startswith('Notes: '):
            for item in note.removeprefix('Notes: ').split(' | '):
                code, _, explanation = item.partition(' ')
                note_items.append(f'{code}: {explanation[:1].upper() + explanation[1:]}')
        else:
            note_items.append(note)
    help_labels['Notes'] = '\n'.join('- ' + note for note in note_items) if note_items else 'No flagged issues.'
    headings = []
    order_label = 'Rank' if ranked else '#'
    for column, label in enumerate((order_label, 'Player', *labels)):
        if label == order_label or label in sort_values:
            heading = (_action_name(label, help_labels[label], floating=True)
                       if label in help_labels else escape(label))
            direction = 'ascending' if label == order_label else 'none'
            headings.append(f'<th scope="col" aria-sort="{direction}"><button type="button"'
                            f' data-sort-column="{column}">'
                            + heading
                            + '</button></th>')
        else:
            headings.append('<th scope="col">' + (_action_name(label, help_labels[label],
                            floating=label == 'Notes') if label in help_labels else escape(label)) + '</th>')
    metadata_line = ' | '.join(sorted(metadata, key=lambda text: not text.startswith('Patch:')))
    ranking_metric = 'DPS' if results[0].encounter_id in {4549, 4551} else 'rDPS'
    if ranked:
        metadata_line += (' | ' if metadata_line else '') + f'Ranked by {ranking_metric}'
    encounter_id = results[0].encounter_id
    fight_name = (ENCOUNTER_NAMES.get(encounter_id, results[0].fight_name)
                  if encounter_id is not None else results[0].fight_name)
    summary = ('<section id="leaderboard"><h2>'
               + escape(job.title() + ' / ' + fight_name + ' ' + report_label) + '</h2>'
               + ('<p class="metadata">' + escape(metadata_line) + '</p>' if metadata_line else '')
               +
               '<p>Select a player to open their full analysis.</p><div class="table-wrap"'
               f' tabindex="0" role="region" aria-label="{report_label}"><table><thead><tr>'
               + ''.join(headings) + '</tr></thead><tbody>'
               + ''.join(table_rows) + '</tbody></table></div>')
    if skipped:
        summary += '<h3>Skipped ranks</h3><ul>' + ''.join(
            f'<li>Rank {rank}: {escape(reason)}</li>' for rank, reason in sorted(skipped)) + '</ul>'
    summary += '</section>'
    css = (_CSS.replace('JOB_COLOUR', JOB_COLOURS.get(job, '#a8d2e6'))
           + '.player-report{margin:24px 0;border:1px solid var(--line);border-radius:10px}'
           '.player-report>summary{cursor:pointer;padding:18px;font-weight:650}'
           '.player-body{padding:20px}.player-body .hero h1{font-size:28px}'
           'aside>nav{max-height:calc(100vh - 130px);overflow-y:auto}'
           '.sidebar-player>summary{cursor:pointer;font-size:13px;padding:5px 0}'
           '.sidebar-player>summary a{display:inline;border:0;padding:0}'
           '.sidebar-player nav{padding:0 0 10px 10px}'
           '.sidebar-player nav a{font-size:12px;padding-top:5px;padding-bottom:5px}'
           '#leaderboard h2,.leaderboard-link{color:var(--accent-text)}'
           '#leaderboard .table-wrap,#leaderboard table{width:100%}'
           'main{border-top:3px solid var(--accent);padding-top:24px}'
           '#leaderboard th button{font:inherit;color:inherit;background:transparent;border:0;'
           'padding:0;cursor:pointer;text-align:inherit}'
           '#leaderboard th button:hover{color:var(--accent-text)}'
           '.header-help-cue{color:var(--accent-text);font-size:10px;font-weight:500}'
           '#leaderboard th button:focus-visible{outline:2px solid var(--accent);outline-offset:4px}'
           '#leaderboard th[aria-sort=ascending] button::after{content:" ↑"}'
           '#leaderboard th[aria-sort=descending] button::after{content:" ↓"}')
    navigation_script = """
const playerReports = [...document.querySelectorAll('details.player-report')];
const playerMenus = [...document.querySelectorAll('details.sidebar-player')];
let activePlayer = '';
function showPlayerMenu(report) {
  if (!report || activePlayer === report.id) return;
  activePlayer = report.id;
  for (const menu of playerMenus) menu.open = menu.dataset.player === report.id;
}
function revealReport() {
  const target = document.getElementById(location.hash.slice(1));
  const report = target?.closest('details.player-report');
  if (report) { report.open = true; showPlayerMenu(report); target.scrollIntoView(); }
}
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (!link) return;
  const target = document.getElementById(link.hash.slice(1));
  const report = target?.closest('details.player-report');
  if (report) { report.open = true; showPlayerMenu(report); }
});
for (const report of playerReports) {
  report.addEventListener('toggle', () => { if (report.open) showPlayerMenu(report); });
}
let scrollPending = false;
window.addEventListener('scroll', () => {
  if (scrollPending) return;
  scrollPending = true;
  requestAnimationFrame(() => {
    scrollPending = false;
    const visible = playerReports.find(report => {
      const bounds = report.getBoundingClientRect();
      return report.open && bounds.top <= 200 && bounds.bottom > 200;
    });
    showPlayerMenu(visible);
  });
}, {passive: true});
window.addEventListener('hashchange', revealReport);
revealReport();
"""
    content = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width, initial-scale=1">'
               f'<title>{escape(JOB_ABBREVIATIONS.get(job, job))} {escape(fight)} {report_label} | FFXIV Potency Analysis</title>'
               '<style>' + css + '</style></head><body><div class="layout"><aside>'
               '<div class="brand">FFXIV potency analysis</div><nav aria-label="Players">'
               + ''.join(navigation) + '</nav></aside><main>' + summary + ''.join(reports)
               + '</main></div><div id="action-tooltip" class="floating-tooltip" role="tooltip" hidden></div>'
               '<script>' + _TOOLTIP_SCRIPT + navigation_script + _SECTION_NAV_SCRIPT
               + _TABLE_SORT_SCRIPT + _TABLE_HOVER_SCRIPT + '</script></body></html>\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding='utf-8')


def write_html_report(result: AnalysisResult, output: Path, *, directory: Path | None = None,
                      anonymous: bool = False, rank: int | None = None) -> None:
    content = render_html_report(result, directory=directory, anonymous=anonymous, rank=rank)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
