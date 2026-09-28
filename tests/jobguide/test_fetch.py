from pathlib import Path

import httpx
import pytest

from ffxiv_potency.jobguide.fetch import fetch_job_guide


def test_fetch_saves_response_without_contacting_live_site(tmp_path: Path) -> None:
    response_body = b"<!doctype html><html><body>fixture</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/machinist/"
        assert request.headers["User-Agent"].startswith("ffxiv-potency/")
        return httpx.Response(200, content=response_body)

    destination = tmp_path / "source.html"
    result = fetch_job_guide(
        "https://example.test/machinist/",
        destination,
        transport=httpx.MockTransport(handler),
    )

    assert result == destination
    assert destination.read_bytes() == response_body


def test_failed_fetch_preserves_saved_source(tmp_path: Path) -> None:
    destination = tmp_path / "source.html"
    destination.write_text("previous snapshot", encoding="utf-8")
    transport = httpx.MockTransport(lambda request: httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        fetch_job_guide("https://example.test/machinist/", destination, transport=transport)

    assert destination.read_text(encoding="utf-8") == "previous snapshot"
