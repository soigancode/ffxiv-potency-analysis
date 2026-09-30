"""A phase-two resource run starts with Battery from an unsaved earlier pull."""

from pathlib import Path
from zipfile import ZipFile

from ffxiv_potency import cli
from ffxiv_potency.analysis import analyze_saved_fight


def test_mch_lindwurm_ii_marks_first_queen_assumed_and_reports_patch(
    tmp_path: Path, capsys,
) -> None:
    directory = tmp_path / "TtaLJrqP4fv986k1/fight-23/source-2"
    directory.mkdir(parents=True)
    prefix = "TtaLJrqP4fv986k1/fight-23/source-2/"
    archive = Path(__file__).parents[1] / "fixtures/logs/mch_lindwurm_ii_resource_run.zip"
    with ZipFile(archive) as z:
        for name in z.namelist():
            if name.startswith(prefix) and name.endswith(".json"):
                (directory / name.removeprefix(prefix)).write_bytes(z.read(name))
    assert cli._fight_provenance(directory) == ("1", "7.4")
    assert cli._fight_date(directory) == "25/04/26"
    actions = Path(__file__).resolve().parents[2] / "data/machinist/7.55/actions.json"
    result = analyze_saved_fight(directory, actions)
    first, second = result.pet_deployments[:2]
    assert first.gauge_spent == 100 and first.gauge_assumed is True
    assert second.gauge_spent == 60 and second.gauge_assumed is False
    cli._print_analysis(result, directory=directory)
    output = capsys.readouterr().out
    assert "Partition: 1\nPatch: 7.4" in output
    assert "100 Battery Gauge (assumed carry-over; unconfirmed by this report)" in output
    cli._compare_directories([directory], actions)
    compared = capsys.readouterr().out
    assert "~ Potency, PPS, Luck, and aLuck include an unconfirmed 100 Battery Gauge carry-over." in compared
