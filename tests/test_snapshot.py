import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.jobguide.snapshot import update_job_guide

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_URL = "https://example.test/jobguide/machinist/"


def test_update_downloads_and_exports_versioned_snapshot(tmp_path: Path) -> None:
    source_bytes = (FIXTURES / "machinist_full_7_5.html").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == SOURCE_URL
        return httpx.Response(200, content=source_bytes)

    result = update_job_guide(
        job="machinist",
        patch="7.55",
        output_root=tmp_path,
        url=SOURCE_URL,
        transport=httpx.MockTransport(handler),
        retrieved_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )

    assert result.source == tmp_path / "machinist" / "7.55" / "source.html"
    assert result.actions == tmp_path / "machinist" / "7.55" / "actions.json"
    assert result.action_count == 40
    assert result.source.read_bytes() == source_bytes

    document = json.loads(result.actions.read_text(encoding="utf-8"))
    assert document["job"] == "machinist"
    assert document["patch"] == "7.55"
    assert document["source"] == {
        "url": SOURCE_URL,
        "retrieved_at": "2026-09-23T12:00:00Z",
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    assert len(document["actions"]) == 40


@pytest.mark.parametrize("patch", ["", "latest", "7", "../7.5", "7.5/other", "7.5"])
def test_update_rejects_unsafe_or_ambiguous_patch(patch: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only patch 7.55"):
        update_job_guide(job="machinist", patch=patch, output_root=tmp_path)
