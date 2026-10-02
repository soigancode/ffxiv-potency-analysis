"""A phase-two resource run starts with Battery from an unsaved earlier pull."""

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import analyze_saved_fight


def test_mch_lindwurm_ii_infers_first_queen_and_reports_patch(
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
    actions = Path(__file__).resolve().parents[2] / "data/jobs/mch/7.4/actions.json"
    result = analyze_saved_fight(directory, actions)
    assert result.echo_status == "absent"
    first, second = result.pet_deployments[:2]
    assert first.gauge_spent == 100 and first.mch_gauge_inferred is True
    assert not first.gauge_assumed
    assert second.gauge_spent == 60 and second.gauge_assumed is False
    cli._print_analysis(result, directory=directory)
    output = capsys.readouterr().out
    assert "Partition: 1 | Ranking patch bracket: 7.4" in output
    assert "Echo: 0%" in output
    assert "Opening Battery: 100 (estimated from Queen damage)" in output
    cli._compare_directories([directory], actions)
    compared = capsys.readouterr().out
    assert "~ Potency, PPS, hit bonus, and luck include Battery estimated from Queen damage." in compared


_OPENING_CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures/audits/mch_lindwurm_ii_opening_queen_audit.json")
    .read_text()
)["cases"]


@pytest.mark.parametrize("case", _OPENING_CASES, ids=lambda case: case["report"])
def test_mch_lindwurm_opening_queen_matches_independent_damage_audit(
    case, tmp_path: Path, mch_actions: Path, extract_fight, capsys,
) -> None:
    extract_fight("mch_lindwurm_ii_opening_queens.zip",
                  f"{case['report']}/fight-{case['fight']}/source-{case['source']}/")
    result = analyze_saved_fight(tmp_path, mch_actions)
    opening = result.pet_deployments[0]
    assert opening.gauge_spent == case["fits"][0]
    prepull = case["first_time"] < case["first_recorded_cast"]
    assert opening.mch_prepull is prepull
    assert opening.mch_gauge_inferred is (prepull or case["assumed"])
    assert not opening.gauge_assumed
    assert result.potency_min == pytest.approx(result.potency_max)
    if prepull and case["report"] != "a-rkPGcq7z1xbMg8vh":
        # The opening active Queen consumed the carried Battery before pull.
        assert result.pet_deployments[1].gauge_spent == 60
    if opening.mch_gauge_inferred:
        cli._print_analysis(result, directory=tmp_path)
        output = capsys.readouterr().out
        assert "estimated from Queen damage" in output
        assert ("Pre-pull" in output) is prepull
