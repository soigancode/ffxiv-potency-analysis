"""Parse report, fight, and source identifiers from FF Logs URLs."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_REPORT_CODE = re.compile(r"(?:a:)?[A-Za-z0-9]+\Z")
_REPORT_PATH = re.compile(r"^/reports/((?:a:)?[A-Za-z0-9]+)$")
_ALLOWED_HOSTS = {"fflogs.com", "www.fflogs.com"}


@dataclass(frozen=True, slots=True)
class ReportReference:
    report_code: str
    fight_id: int
    source_id: int


@dataclass(frozen=True, slots=True)
class ReportSelection:
    report_code: str
    fight_id: int | None
    source_id: int | None


def valid_report_code(code: str) -> bool:
    """Accept standard and FF Logs anonymous report codes."""
    return _REPORT_CODE.fullmatch(code) is not None


def report_directory_name(code: str) -> str:
    """Avoid a colon in paths so anonymous reports work on Windows too."""
    return "a-" + code[2:] if code.startswith("a:") else code


def report_code_from_directory(name: str) -> str | None:
    code = "a:" + name[2:] if name.startswith("a-") else name
    return code if valid_report_code(code) else None


def _positive_integer(query: dict[str, list[str]], name: str) -> int:
    values = query.get(name, [])
    if len(values) != 1:
        raise ValueError(f"FF Logs URL must contain exactly one {name!r} parameter")
    try:
        value = int(values[0])
    except ValueError as exc:
        raise ValueError(f"FF Logs URL parameter {name!r} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"FF Logs URL parameter {name!r} must be positive")
    return value


def parse_report_url(value: str) -> ReportReference:
    """Extract the selected report, fight, and player source from a copied URL."""

    selection = parse_report_selection_url(value)
    if selection.fight_id is None:
        raise ValueError("FF Logs URL must contain exactly one 'fight' parameter")
    if selection.source_id is None:
        raise ValueError("FF Logs URL must contain exactly one 'source' parameter")
    return ReportReference(selection.report_code, selection.fight_id, selection.source_id)


def parse_report_selection_url(value: str) -> ReportSelection:
    """Accept a report URL with zero, one, or both selections."""

    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("expected an https://www.fflogs.com/reports/... URL")
    match = _REPORT_PATH.fullmatch(parsed.path.rstrip("/"))
    if match is None:
        raise ValueError("FF Logs URL must point to /reports/<report-code>")

    query = parse_qs(parsed.query, keep_blank_values=True)
    return ReportSelection(
        report_code=match.group(1),
        fight_id=_positive_integer(query, "fight") if "fight" in query else None,
        source_id=_positive_integer(query, "source") if "source" in query else None,
    )


def parse_report_selection(value: str) -> ReportSelection:
    """Accept a bare report ID or a report URL with optional selections."""
    if valid_report_code(value):
        return ReportSelection(value, None, None)
    return parse_report_selection_url(value)
