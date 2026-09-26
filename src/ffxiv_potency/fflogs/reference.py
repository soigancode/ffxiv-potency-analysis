"""Parse report, fight, and source identifiers from FF Logs URLs."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_REPORT_PATH = re.compile(r"^/reports/([A-Za-z0-9]+)$")
_ALLOWED_HOSTS = {"fflogs.com", "www.fflogs.com"}


@dataclass(frozen=True, slots=True)
class ReportReference:
    report_code: str
    fight_id: int
    source_id: int


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

    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("expected an https://www.fflogs.com/reports/... URL")
    match = _REPORT_PATH.fullmatch(parsed.path.rstrip("/"))
    if match is None:
        raise ValueError("FF Logs URL must point to /reports/<report-code>")

    query = parse_qs(parsed.query, keep_blank_values=True)
    return ReportReference(
        report_code=match.group(1),
        fight_id=_positive_integer(query, "fight"),
        source_id=_positive_integer(query, "source"),
    )
