"""Named gear overrides reach each CLI analysis entry point."""

from pathlib import Path

from ffxiv_potency import cli


def test_analyse_gear_override_reaches_calculation(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(cli, "_resolve_analysis_directory", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(cli, "_source_job", lambda _: "machinist")
    monkeypatch.setattr(cli, "_actions_for_job", lambda *args: Path("actions.json"))
    monkeypatch.setattr(cli, "_verify_supported_fight", lambda _: None)
    monkeypatch.setattr(cli, "_print_analysis", lambda *args, **kwargs: None)

    def analyze(directory, actions, *, gear=None):
        calls.append(gear)

    monkeypatch.setattr(cli, "analyze_saved_fight", analyze)
    assert cli.main(["analyse", str(tmp_path), "--gear", "savage_7_4"]) == 0
    assert calls == ["savage_7_4"]


def test_compare_gear_override_reaches_download_pipeline(monkeypatch) -> None:
    calls = []
    urls = ["https://www.fflogs.com/reports/abc?fight=1&source=2",
            "https://www.fflogs.com/reports/def?fight=1&source=3"]

    def compare(urls, output, actions, progress, *, gear=None):
        calls.append(gear)
        return ()

    monkeypatch.setattr(cli, "_download_and_compare", compare)
    assert cli.main(["compare", *urls, "--gear", "relic_7_55"]) == 0
    assert calls == ["relic_7_55"]
