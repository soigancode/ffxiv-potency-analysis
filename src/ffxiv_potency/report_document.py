"""Presentation events shared by terminal and HTML reports."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

ACTION_HEADERS = {
    "Goring": "Goring Blade", "Faith": "Blade of Faith", "Truth": "Blade of Truth",
    "Valor": "Blade of Valor", "Honor": "Blade of Honor", "Scorn": "Circle of Scorn",
    "IR spenders": "Fell Cleave / Decimate using Inner Release charges",
    "NC": "Inner Chaos / Chaotic Cyclone (Nascent Chaos)",
    "Rend": "Primal Rend", "Ruination": "Primal Ruination", "Wrath": "Primal Wrath",
    "Upheaval": "Upheaval / Orogeny",
    "Empyreal": "Empyreal Arrow", "Refulgent": "Refulgent Arrow",
    "Resonant": "Resonant Arrow", "Blast": "Blast Arrow", "Encore": "Radiant Encore",
    "Apex": "Apex Arrow", "PP": "Pitch Perfect",
    "Anchor": "Air Anchor", "Full Metal": "Full Metal Field",
    "Blazing": "Blazing Shot", "Crossbow": "Auto Crossbow",
    "Starfall": "Starfall Dance", "Dawn": "Dance of the Dawn",
    "Finishing": "Finishing Move", "Fan III": "Fan Dance III", "Fan IV": "Fan Dance IV",
    "Saber": "Saber Dance", "Fan I": "Fan Dance", "Fan II": "Fan Dance II",
}


@dataclass(frozen=True, slots=True)
class ReportText:
    text: str
    notes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ReportTable:
    labels: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    notes: tuple[str, ...]
    indent: str
    cell_notes: tuple[tuple[int, int, str], ...] = ()
    cell_states: tuple[tuple[int, int, str], ...] = ()


ReportBlock = ReportText | ReportTable
_blocks: ContextVar[list[ReportBlock] | None] = ContextVar("report_blocks", default=None)


@contextmanager
def collect_report() -> Iterator[list[ReportBlock]]:
    """Collect report events without redirecting process-wide stdout."""
    blocks: list[ReportBlock] = []
    token = _blocks.set(blocks)
    try:
        yield blocks
    finally:
        _blocks.reset(token)


def emit_text(*values: str, notes: tuple[tuple[str, str], ...] = ()) -> None:
    blocks = _blocks.get()
    if blocks is None:
        print(*values)
    else:
        blocks.append(ReportText(" ".join(values), notes))


def emit_table(labels: tuple[str, ...], rows: list[tuple[str, ...]],
               notes: list[str] | None, indent: str,
               cell_notes: dict[tuple[int, int], str] | None = None,
               cell_states: dict[tuple[int, int], str] | None = None) -> bool:
    blocks = _blocks.get()
    if blocks is None:
        return False
    blocks.append(ReportTable(labels, tuple(rows), tuple(notes or ()), indent,
                              tuple((row, col, note) for (row, col), note in (cell_notes or {}).items()),
                              tuple((row, col, state) for (row, col), state in (cell_states or {}).items())))
    return True
