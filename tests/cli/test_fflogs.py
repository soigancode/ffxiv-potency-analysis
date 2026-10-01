"""Tests for fflogs behavior."""

from pathlib import Path

from ffxiv_potency import cli
from ffxiv_potency.fflogs import DownloadResult
from ffxiv_potency.fflogs.client import RateLimitUsage


def test_fflogs_limit_displays_hourly_usage(monkeypatch, capsys) -> None:
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def rate_limit(self):
            return RateLimitUsage(3600, 125.25, 83)

    monkeypatch.setattr(cli.FFLogsClient, "from_environment", lambda: FakeClient())
    assert cli.main(["fflogs", "limit"]) == 0
    assert capsys.readouterr().out == (
        "FF Logs API usage:\n"
        "  Spent this hour: 125.25 / 3,600 points\n"
        "  Resets in: 01m23s\n"
    )



def test_fflogs_limit_rejects_fight_argument(capsys) -> None:
    assert cli.main(["fflogs", "limit", "m11s"]) == 1
    assert "takes no fight or rank" in capsys.readouterr().err



def test_cli_accepts_copied_fflogs_url(monkeypatch, tmp_path: Path, capsys) -> None:
    url = "https://www.fflogs.com/reports/abc123?fight=9&type=damage-done&source=18"
    directory = tmp_path / "abc123" / "fight-9" / "source-18"
    expected = DownloadResult(
        directory=directory,
        fight=directory / "fight.json",
        master_data=directory / "master-data.json",
        damage_events=directory / "damage-events.json",
        cast_events=directory / "cast-events.json",
        rankings=directory / "rankings.json",
        damage_event_count=20,
        cast_event_count=10,
    )

    def fake_download(reference, output_root: Path) -> DownloadResult:
        assert reference.report_code == "abc123"
        assert reference.fight_id == 9
        assert reference.source_id == 18
        assert output_root == tmp_path
        return expected

    monkeypatch.setattr(cli, "download_report_events", fake_download)

    assert cli.main(["fflogs", url, "--output", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert f"Saved fight data: {directory}" in output
    assert "Damage events: 20" in output
    assert "Cast events: 10" in output

