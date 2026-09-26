"""HTTP access for official FFXIV job-guide pages."""

from pathlib import Path

import httpx

DEFAULT_USER_AGENT = "ffxiv-potency/0.1 (personal job-guide snapshot tool)"


def fetch_job_guide(
    url: str,
    destination: Path,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Download *url* once and save its HTML at *destination*.

    Downloading is intentionally separate from parsing so an exact source
    snapshot can be retained and tests can operate entirely offline.
    """

    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html"}
    with httpx.Client(
        headers=headers, timeout=20.0, follow_redirects=True, transport=transport
    ) as client:
        response = client.get(url)
        response.raise_for_status()

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination
