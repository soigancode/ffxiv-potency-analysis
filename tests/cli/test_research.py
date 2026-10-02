"""Research downloads cover selected leaderboard partitions without analysis."""

from pathlib import Path
from threading import Barrier, get_ident

import pytest

from ffxiv_potency import cli
from ffxiv_potency.fflogs import FFLogsError, ReportReference
from ffxiv_potency.fflogs.partitions import current_partition
from ffxiv_potency.jobs import JOB_NAMES, job_code, job_name


@pytest.mark.parametrize("code,name", JOB_NAMES.items())
def test_combat_job_names_use_consistent_abbreviations(code, name):
    assert job_code(name) == code
    assert job_code(code.upper()) == code
    assert job_name(code) == name


@pytest.mark.parametrize(
    "job,code,spec", [("NIN", "nin", "Ninja"), ("Dark Knight", "drk", "DarkKnight")]
)
def test_research_downloads_all_unique_leaderboards(monkeypatch, tmp_path, capsys, job, code, spec):
    monkeypatch.chdir(tmp_path)
    lookups = []
    downloads = []

    def lookup(encounter, selected_job, *, limit, **options):
        assert selected_job == spec
        assert limit == 3
        selected = options.get("partition")
        assert selected == (1 if encounter in {101, 103} else None)
        lookups.append((encounter, current_partition(encounter, selected)))
        return tuple(
            (rank, ReportReference(f"report{encounter}", rank, rank)) for rank in (1, 2, 3)
        ), ()

    def download(url, output, *, announce, include_targetability):
        assert output == Path("data/research") / code
        assert announce is False
        assert include_targetability is True
        downloads.append(url)
        return output / "saved-source"

    def no_analysis(*args, **kwargs):
        raise AssertionError("research must not require job data or calculate potency")

    monkeypatch.setattr(cli, "accessible_ranked_sources", lookup)
    monkeypatch.setattr(cli, "_resolve_analysis_directory", download)
    monkeypatch.setattr(cli, "analyze_saved_fight", no_analysis)
    monkeypatch.setattr(cli, "_actions_for_job", no_analysis)
    assert cli.main(["research", job]) == 0
    assert lookups == [
        (id_, 1 if id_ in {101, 103} else current_partition(id_))
        for id_ in dict.fromkeys(cli.CURRENT_FIGHTS.values())
    ]
    assert len(downloads) == len(lookups) * 3 == 33
    assert "Saved 33 research logs" in capsys.readouterr().out


def test_research_preserves_successes_and_continues_after_failures(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "CURRENT_FIGHTS", {"m9s": 101, "m10s": 102, "umad": 1085, "dmu": 1085})
    attempted = []

    def lookup(encounter, job, **options):
        if encounter == 102:
            raise FFLogsError("leaderboard unavailable")
        return tuple(
            (rank, ReportReference(f"report{encounter}", rank, 7)) for rank in (1, 2, 4)
        ), ((3, "private log"),)

    def download(url, output, **options):
        reference = cli.parse_report_url(url)
        attempted.append(reference)
        if reference.fight_id == 2:
            raise FFLogsError("download unavailable")
        directory = cli._saved_directory(output, reference)
        directory.mkdir(parents=True)
        (directory / "fight.json").write_text("{}")
        return directory

    monkeypatch.setattr(cli, "accessible_ranked_sources", lookup)
    monkeypatch.setattr(cli, "_resolve_analysis_directory", download)
    output = tmp_path / "samples"
    assert cli.main(["research", "dnc", "--output", str(output)]) == 1
    assert len(attempted) == 6
    assert len(list(output.glob("dnc/*/fight-*/source-*/fight.json"))) == 4
    captured = capsys.readouterr()
    assert "leaderboard unavailable" in captured.err
    assert "download unavailable" in captured.err
    assert "skipped rank 3: private log" in captured.err
    assert "Saved 4 research logs" in captured.out


def test_research_rejects_unknown_job_before_network(monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("invalid input must not contact FF Logs")

    monkeypatch.setattr(cli, "accessible_ranked_sources", no_network)
    assert cli.main(["research", "../logs"]) == 1
    assert "unknown job" in capsys.readouterr().err


def test_research_downloads_three_logs_concurrently(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CURRENT_FIGHTS", {"m9s": 101})
    ranked = tuple((rank, ReportReference(f"report{rank}", 1, 7)) for rank in (1, 2, 3))
    monkeypatch.setattr(cli, "accessible_ranked_sources", lambda *args, **kwargs: (ranked, ()))
    barrier = Barrier(3)
    workers = set()

    def download(url, output, **options):
        workers.add(get_ident())
        barrier.wait(timeout=5)
        return output

    monkeypatch.setattr(cli, "_resolve_analysis_directory", download)
    assert cli.main(["research", "war", "--output", str(tmp_path)]) == 0
    assert len(workers) == 3


def test_research_deduplicates_downloads_to_the_same_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CURRENT_FIGHTS", {"m9s": 101})
    reference = ReportReference("report1", 1, 7)
    monkeypatch.setattr(
        cli,
        "accessible_ranked_sources",
        lambda *args, **kwargs: (
            ((1, reference), (2, reference)),
            (),
        ),
    )
    calls = []

    def download(url, output, **options):
        calls.append(url)
        return output

    monkeypatch.setattr(cli, "_resolve_analysis_directory", download)
    assert cli.main(["research", "war", "--output", str(tmp_path)]) == 0
    assert len(calls) == 1
