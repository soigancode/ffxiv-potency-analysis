"""PLD aliases, automatic selection, gear overrides and report conventions."""

import re
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis.cooldown_timing import CooldownTiming
from ffxiv_potency.analysis.models import (
    AnalysisResult,
    HitOutcomeSummary,
    PotionSummary,
)
from ffxiv_potency.analysis.pld.summary import PldDotSummary, PldSummary
from ffxiv_potency.analysis.ranged import RangedChain
from ffxiv_potency.fflogs.selection import ReportFight, ReportPlayer
from ffxiv_potency.jobguide import SnapshotResult

ROOT = Path(__file__).resolve().parents[2]


def test_melee_downtime_labels_holy_spirit_cast_evidence(capsys):
    pld = PldSummary(
        (), (), (),
        (RangedChain(10.111, "Holy Spirit", 2.497, "Holy Spirit", 2.499,
                     ("Holy Spirit", "Shield Lob", "Holy Spirit"), (2.498, 2.496)),),
        PldDotSummary(0, 0, 0, 0),
        ((7.614, "instant"), (10.111, "hard cast"), (15.105, "hard cast"),
         (17.604, "unconfirmed")),
    )
    result = AnalysisResult(
        fight_name="Test", encounter_id=1, source_name="Player", ndps=None,
        duration_seconds=60, raw_damage_events=0, landed_damage_events=0,
        matched_damage_events=0, potency_min=0, potency_max=0, actions=(),
        auto_attacks=(), pet_deployments=(), hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(), pld=pld,
    )
    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert ("    00m10s: HS (instant) -> 2.50s -> HS (hard-cast) -> 2.50s -> Shield Lob"
            " -> 2.50s -> HS (hard-cast) -> 2.50s -> HS (unconfirmed)") in output


@pytest.mark.parametrize("alias", ["pld", "PLD", "paladin", "PALADIN"])
def test_jobguide_accepts_paladin_aliases(tmp_path, monkeypatch, capsys, alias):
    def update(**kwargs):
        assert kwargs["job"] == "paladin" and kwargs["patch"] == "7.56"
        return SnapshotResult(tmp_path / "source.html", tmp_path / "actions.json", 39)

    monkeypatch.setattr(cli, "update_job_guide", update)
    assert cli.main(["jobguide", alias, "--output", str(tmp_path)]) == 0
    assert "Wrote 39 actions:" in capsys.readouterr().out


def test_cli_analyse_compare_and_gear_override(tmp_path, monkeypatch, capsys):
    shutil.copytree(ROOT / "data/jobs/pld", tmp_path / "data/jobs/pld")
    logs = tmp_path / "data/logs"
    with ZipFile(ROOT / "tests/fixtures/logs/pld_dancing_mad.zip") as archive:
        archive.extractall(logs)
    monkeypatch.chdir(tmp_path)
    first = logs / "dzyx6FtjcQXMDJP3/fight-13/source-98"
    assert cli.main(["analyse", str(first)]) == 0
    output = capsys.readouterr().out
    assert "Gear: 7.55 Real BiS (assumed)" in output
    assert "Blade of Valor: unenhanced" in output
    assert "Fight or Flight:" in output and "Circle of Scorn:" in output
    assert "rDPS/nDPS:" in output
    assert "fight-13" not in output and "Fight ID" not in output
    assert "\nSpell casts:\n  Spell" in output
    spell_table = output.split("\nSpell casts:\n", 1)[1].split(
        "  Unconfirmed cast time", 1,
    )[0]
    effect_order = {"Divine Might": 0, "Requiescat": 1, "None": 2}
    spell_rows = [re.split(r"\s{2,}", row.strip()) for row in spell_table.splitlines()[1:]]
    assert {row[1] for row in spell_rows} == set(effect_order)
    spell_effects = [(row[0], effect_order[row[1]]) for row in spell_rows]
    assert spell_effects == sorted(spell_effects)
    assert "\nCircle of Scorn:\n  Applications" in output
    assert "\n    07m32s:" in output and " -> 3.48s -> HS (hard-cast) -> 1.52s -> " in output
    assert output.isascii()
    assert output.index("Direct Hit") < output.index("Critical Hit")
    assert cli.main(["analyse", str(first), "--gear", "relic_7_55"]) == 0
    assert "Gear: 7.55 Relic BiS (user-selected)" in capsys.readouterr().out
    assert cli.main(["compare",
                     "https://www.fflogs.com/reports/dzyx6FtjcQXMDJP3?fight=13&source=98",
                     "https://www.fflogs.com/reports/kp4CzadVbJXQ216Z?fight=7&source=23"]) == 0
    output = capsys.readouterr().out
    assert "rDPS/nDPS" in output and "dPPS" in output
    assert "aHB" in output and "aLuck" in output


@pytest.mark.parametrize("alias", ["pld", "paladin"])
def test_leaderboard_resolves_paladin_alias(tmp_path, monkeypatch, capsys, alias):
    def lookup(encounter, job, **kwargs):
        assert encounter == 1085 and job == "paladin"
        raise ValueError("Paladin rank lookup reached")

    monkeypatch.setattr(cli, "accessible_ranked_sources", lookup)
    assert cli.main(["fflogs", alias, "dmu", "--output", str(tmp_path)]) == 1
    assert "Paladin rank lookup reached" in capsys.readouterr().err


def test_report_selection_accepts_paladin_without_prompt(monkeypatch):
    from ffxiv_potency.fflogs import ReportReference

    fight = ReportFight(13, "Dancing Mad", 1085, 1109, True,
                        (ReportPlayer(98, "Simba Aslanii", "Paladin"),))
    monkeypatch.setattr(cli, "report_fights", lambda _: (fight,))

    def fail_prompt(*args):
        raise AssertionError("the only supported Paladin must be selected automatically")

    monkeypatch.setattr("builtins.input", fail_prompt)
    assert cli._select_report_reference("https://www.fflogs.com/reports/abc123") == ReportReference("abc123", 13, 98)


def test_alignment_findings_sort_by_gain_and_report_sections_by_importance(capsys):
    from ffxiv_potency.analysis.pld.alignment import summarize_alignment
    from ffxiv_potency.analysis.pld.buffs import FIGHT_OR_FLIGHT

    alignment = summarize_alignment(
        [(21000, 'Expiacion', 450, False), (51000, 'Expiacion', 450, False),
         (22000, 'Blade of Honor', 1000, False),
         (5000, 'Imperator', 580, False), (1000, 'Confiteor', 1000, True)],
        {FIGHT_OR_FLIGHT: ((0, 20000, 1.25),)}, 0, 60000, 1.25,
    )
    result = AnalysisResult(
        fight_name='Test', encounter_id=1, source_name='Player', ndps=None,
        duration_seconds=60, raw_damage_events=0, landed_damage_events=0,
        matched_damage_events=0, potency_min=0, potency_max=0, actions=(),
        auto_attacks=(), pet_deployments=(), hit_outcomes=HitOutcomeSummary(0, 0, 0, 0),
        potion=PotionSummary(0, 0, 0, 0, 0), unmatched=(), ghosted=(),
        pld=PldSummary((), (), (), (), PldDotSummary(0, 0, 0, 0), alignment=alignment,
                       cooldown_timing=(CooldownTiming('Fight or Flight', 18.4, 6.2),
                                        CooldownTiming('Imperator', None, None),
                                        CooldownTiming('Intervene', 8.2, 2.7, True))),
    )
    cli._print_analysis(result)
    output = capsys.readouterr().out
    summary = output.split('Actions outside Fight or Flight:\n', 1)[1].split(
        '  Potency excludes Fight or Flight.', 1,
    )[0]
    rows = [re.split(r'\s{2,}', row.strip()) for row in summary.splitlines()]
    assert rows == [
        ['Action', 'Uses', 'Potency', 'Potential buff gain'],
        ['Blade of Honor', '1', '1,000.0', '250.0'],
        ['Expiacion', '2', '900.0', '225.0'],
        ['Imperator', '1', '580.0', '145.0'],
    ]
    assert 'Snapshot ' not in summary
    assert '\n  Intervene: 0 uses\n\n  Cooldown timing:' in output
    assert output.index('Cooldown timing:') < output.index('Landed potency inside')
    timing = output.split('  Cooldown timing:\n', 1)[1].split(
        '  Timing starts after', 1,
    )[0]
    assert [re.split(r'\s{2,}', row.strip()) for row in timing.splitlines()] == [
        ['Action', 'Ready while targetable', 'Longest delay'],
        ['Fight or Flight', '18.4s', '6.2s'],
        ['Imperator', 'n/a', 'n/a'],
        ['Intervene', '8.2s', '2.7s'],
    ]
    headings = ['Fight or Flight and offensive abilities:', 'Ready effects and spell charges:',
                'Imperator/Requiescat follow-ups:', 'Spell casts:', 'Circle of Scorn:',
                'Melee downtime:']
    positions = [output.index('\n' + heading) for heading in headings]
    assert positions == sorted(positions)
    assert output.isascii()
