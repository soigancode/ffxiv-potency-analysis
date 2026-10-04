"""Presentation events shared by terminal and HTML reports."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportText:
    text: str


@dataclass(frozen=True, slots=True)
class ReportTable:
    labels: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    notes: tuple[str, ...]
    indent: str
    cell_notes: tuple[tuple[int, int, str], ...] = ()


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


def emit_text(*values: str) -> None:
    blocks = _blocks.get()
    if blocks is None:
        print(*values)
    else:
        blocks.append(ReportText(" ".join(values)))


def emit_table(labels: tuple[str, ...], rows: list[tuple[str, ...]],
               notes: list[str] | None, indent: str,
               cell_notes: dict[tuple[int, int], str] | None = None) -> bool:
    blocks = _blocks.get()
    if blocks is None:
        return False
    blocks.append(ReportTable(labels, tuple(rows), tuple(notes or ()), indent,
                              tuple((row, col, note) for (row, col), note in (cell_notes or {}).items())))
    return True
