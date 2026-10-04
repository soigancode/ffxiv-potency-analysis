"""Self-contained dark HTML reports, rendered from shared presentation events."""

import json
import re
from html import escape
from pathlib import Path

from .analysis.models import AnalysisResult
from .report_document import ReportBlock, ReportTable, ReportText, collect_report
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
    "Luck baseline": (
        "Expected Luck from the configured Direct Hit and Critical Hit stats, before rate buffs. "
        "Luck is weighted by potency. A score of 100% means every eligible hit was both direct and critical."
    ),
    "Hit Bonus": (
        "The potency-weighted damage bonus from recorded Direct Hits and Critical Hits, including guaranteed outcomes. "
        "For example, +48% means those outcomes add 48% damage over the same attacks without their DH/Crit bonuses."
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
 border:1px solid var(--line);border-radius:7px;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums;
 white-space:nowrap}th,td{padding:11px 14px;text-align:right;border-bottom:1px solid var(--line)}
th{font-size:11px;color:var(--muted);letter-spacing:.03em;font-weight:650;background:#202226}
th:first-child,td:first-child{text-align:left}tbody tr:last-child td{border-bottom:0}
th:first-child,td:first-child{position:sticky;left:0;z-index:1;background:var(--panel)}
th:first-child{background:#202226}
tbody tr:nth-child(even){background:#1e2023}tbody tr:hover{background:#24272b}
tbody tr:nth-child(even) td:first-child{background:#1e2023}
tr.needs-attention{background:color-mix(in srgb,var(--accent) 7%,var(--panel))}
tr.needs-attention td:first-child{box-shadow:inset 3px 0 var(--accent);
 background:color-mix(in srgb,var(--accent) 7%,var(--panel))}
td[data-state=shortfall],td[data-state=missing-hit]{color:var(--accent-text);
 font-weight:750;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:5px}
td[data-state]{position:relative;outline-offset:-3px}
td[data-state=shortfall]::after,td[data-state=missing-hit]::after{content:" !";
 font-size:11px;font-weight:800;text-decoration:none}
td[data-state]:hover::before,td[data-state]:focus::before{content:attr(title);position:absolute;
 right:0;bottom:100%;width:280px;padding:10px 12px;background:var(--bg);border:1px solid var(--accent);
 border-radius:6px;color:var(--text);font:12px/1.5 system-ui,sans-serif;text-align:left;
 white-space:normal;z-index:3;box-shadow:0 4px 16px #0008}
.attention-key{font-size:12px;color:var(--muted)}
.metric-help{display:inline-block;position:relative;margin-left:6px}
.metric-help button{font:inherit;color:var(--accent-text);background:none;border:0;
 padding:0;cursor:help}.metric-help button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.metric-tooltip{display:none;position:absolute;left:0;bottom:calc(100% + 8px);
 width:320px;max-width:calc(100vw - 48px);padding:12px 14px;border:1px solid var(--accent);
 border-radius:7px;background:var(--bg);color:var(--text);font-size:13px;font-weight:400;
 line-height:1.5;z-index:4;box-shadow:0 4px 16px #0008}
.metric-help:hover .metric-tooltip,.metric-help:focus-within .metric-tooltip{display:block}
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
 .layout{display:block;padding:0}aside,.metric-help{display:none}section,.assumptions{border:0;padding:8px 0;
 margin:12px 0}.table-wrap{overflow:visible}th{background:#eee}th,td{padding:5px 8px;
 white-space:normal}h2,h3{break-after:avoid}tr{break-inside:avoid}details:not([open])>*:not(summary){display:block}}
"""


def _table(block: ReportTable) -> str:
    header = "".join(f'<th scope="col">{escape(label)}</th>' for label in block.labels)
    rows = []
    cell_notes = {(row, col): note for row, col, note in block.cell_notes}
    flagged = False
    burst = block.labels[:3] == ("Burst", "Buff start", "Buff end") and "Imperator" in block.labels
    for i, row in enumerate(block.rows):
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
                    reason = f"{missed} fewer casts than conservative opportunities. This is not a confirmed rotation loss."
            if burst and block.labels[col] == "Completion":
                if value == "n/a":
                    state, reason = "unknown", "Incomplete expectations or no conservative opportunities"
                elif float(value.rstrip("%")) < 100:
                    state = "shortfall"
                    reason = "Some conservative cast opportunities were not completed. Missing landed hits are highlighted separately."
            if (i, col) in cell_notes:
                state = "missing-hit"
                reason = (reason + " " + cell_notes[i, col]).strip()
            attributes = ""
            if state:
                attributes = (f' data-state="{state}" tabindex="0" title="{escape(reason, quote=True)}"'
                              f' aria-label="{escape(block.labels[col] + ": " + value + ". " + reason, quote=True)}"')
            if state in {"shortfall", "missing-hit"}:
                row_flagged = flagged = True
            cells.append(f"<td{attributes}>{escape(value)}</td>")
        rows.append(('<tr class="needs-attention">' if row_flagged else "<tr>") + "".join(cells) + "</tr>")
        if i < len(block.notes) and block.notes[i]:
            rows.append(f'<tr><td class="row-note" colspan="{len(block.labels)}">'
                        + escape(block.notes[i]).replace("\n", "<br>") + "</td></tr>")
    return ('<div class="table-wrap" tabindex="0" role="region" aria-label="'
            + escape(", ".join(block.labels), quote=True) + '"><table><thead><tr>'
            + header + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            + ('<p class="attention-key">! = fewer casts than opportunities, or casts without landed hits. '
               'Hover or focus a marked cell for details. Encounter context may explain missing damage.</p>'
               if flagged else ""))


def _line(line: str) -> str:
    if not line.strip():
        return '<div class="spacer" aria-hidden="true"></div>'
    text = line.strip()
    if text.endswith(":"):
        return f"<h3>{escape(text[:-1])}</h3>"
    indent = len(line) - len(line.lstrip())
    css = "report-line" + (" nested deep" if indent >= 6 else " nested" if indent >= 4 else "")
    label = text.split(":", 1)[0]
    help_marker = ""
    if label in _METRIC_HELP:
        help_id = "help-" + label.lower().replace(" ", "-")
        help_marker = (f'<span class="metric-help"><button type="button" aria-label="About {label}" '
                       f'aria-describedby="{help_id}">(?)</button>'
                       f'<span class="metric-tooltip" role="tooltip" id="{help_id}">'
                       + escape(_METRIC_HELP[label]) + "</span></span>")
    return f'<p class="{css}">{escape(text)}{help_marker}</p>'


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


def render_html_report(result: AnalysisResult, *, directory: Path | None = None,
                       anonymous: bool = False, rank: int | None = None) -> str:
    """Render existing results without changing calculations or cached models."""
    from .cli import CURRENT_FIGHTS, _display_player_name, _source_job

    job = result.execution.job if result.execution else (_source_job(directory) if directory else "")
    if not job and result.pld:
        job = "paladin"
    colour = JOB_COLOURS.get(job, "#a8d2e6")
    player = re.sub(r"\x1b\[[0-9;]*m", "", _display_player_name(result.source_name, anonymous=anonymous))
    rank_label = f"Rank {rank}" if rank is not None else _saved_rank(directory, result, job)
    fight_label = next((alias.upper() for alias, encounter in CURRENT_FIGHTS.items()
                        if encounter == result.encounter_id), result.fight_name)
    with collect_report() as blocks:
        print_analysis(result, directory=directory, anonymous=anonymous, rank=rank)

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
                current.append(ReportText(line))

    navigation = []
    content = []
    for i, (heading, section_blocks) in enumerate(sections, 1):
        anchor = f"section-{i}"
        navigation.append(f'<a href="#{anchor}">{escape(heading)}</a>')
        body = "".join(_table(block) if isinstance(block, ReportTable) else _line(block.text)
                       for block in section_blocks)
        if heading == "Data and assumptions":
            content.append(f'<details class="assumptions" id="{anchor}">'
                           f"<summary>{escape(heading)}</summary>{body}</details>")
        else:
            css = ' class="execution"' if heading == "Execution summary" else ""
            content.append(f'<section id="{anchor}"{css} aria-labelledby="heading-{i}">'
                           f'<h2 id="heading-{i}">{escape(heading)}</h2>{body}</section>')
    metadata = []
    for block in intro:
        if isinstance(block, ReportText) and block.text.strip():
            if block.text.startswith("Player:"):
                continue
            css = "headline" if block.text.startswith("Landed potency:") else "metadata"
            metadata.append(f'<p class="{css}">{escape(block.text.strip())}</p>')
    job_label = JOB_ABBREVIATIONS.get(job, "Analysis")
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(player)} - {escape(fight_label)} | FFXIV Potency Analysis</title>"
            + "<style>" + _CSS.replace("JOB_COLOUR", colour) + "</style></head><body>"
            + '<div class="layout"><aside><div class="brand">FFXIV potency analysis</div>'
            + '<nav aria-label="Report sections">' + "".join(navigation) + "</nav></aside><main>"
            + '<header class="hero"><div class="eyebrow">' + escape(job_label)
            + (" / " + escape(rank_label) if rank_label else "") + "</div><h1>" + escape(player)
            + "</h1>" + "".join(metadata) + "</header>" + "".join(content)
            + "<footer>FFXIV potency analysis / Counts and diagnostics follow the recorded evidence.</footer>"
            + "</main></div></body></html>\n")


def write_html_report(result: AnalysisResult, output: Path, *, directory: Path | None = None,
                      anonymous: bool = False, rank: int | None = None) -> None:
    content = render_html_report(result, directory=directory, anonymous=anonymous, rank=rank)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
