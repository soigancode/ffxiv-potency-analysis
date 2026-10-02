"""Audit all three supplied Dancer clears with independent potency and Luck sums."""

from pathlib import Path
from zipfile import ZipFile

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _print_analysis

CASES = [
    ("zVBFXa9TYGn1wh8d/fight-6/source-4/", "Luuqu Iko", 319, 511, 46, "7.55"),
    ("6mCVqpY1HN47daLG/fight-10/source-9/", "Skye Uwu", 310, 491, 45, "7.56"),
    ("VWJv7x9DbRa4ktH6/fight-7/source-4/", "Felix Austed", 314, 488, 45, "7.56"),
]


def extract(directory: Path, prefix: str) -> None:
    with ZipFile("tests/fixtures/logs/dnc_dancing_mad.zip") as archive:
        for member in archive.namelist():
            if member.startswith(prefix) and member.endswith(".json"):
                (directory / Path(member).name).write_bytes(archive.read(member))


@pytest.mark.parametrize("prefix,player,attacks,matched,finishes,patch", CASES)
def test_dancer_clear_totals_luck_and_output(
    tmp_path, capsys, audit_dnc, prefix, player, attacks, matched, finishes, patch
):
    expected = {
        "Luuqu Iko": (93, 47, 47, 48, 29, 48),
        "Skye Uwu": (91, 49, 49, 50, 27, 46),
        "Felix Austed": (87, 45, 45, 46, 24, 43),
    }[player]
    result = audit_dnc(
        tmp_path,
        "dnc_dancing_mad.zip",
        prefix.rstrip("/"),
        (
            player,
            "relic_7_55",
            matched,
            attacks,
            4,
            finishes,
            expected[0],
            expected[1],
            expected[2],
            expected[4],
        ),
        (0,),
    )
    if player == "Felix Austed":
        assert result.execution is not None
        last_dance = next(r for r in result.execution.ready if r.name == "Last Dance")
        assert (last_dance.grants, last_dance.uses, last_dance.overwritten, last_dance.remaining) == (35, 34, 0, 1)
    assert result.source_name == player
    assert result.played_patch == patch
    assert result.gear_id == "relic_7_55"
    assert result.unmatched == ()
    assert result.matched_damage_events == matched
    assert result.auto_attacks[0].hits == attacks
    assert result.auto_attacks[0].weapon_delay_seconds == 3.12
    assert result.auto_attacks[0].potency_per_hit == pytest.approx(90 * 216 / 208 / 1.2)
    assert result.potion.uses == 4
    assert result.potion.item is not None and result.potion.item.recorded
    assert len(result.dnc_finishes) == finishes
    assert "Improvisation" not in dict(result.ghosted)
    proc = result.dnc_procs
    assert proc is not None
    assert (
        proc.feather_trials,
        proc.feathers_used,
        proc.feathers_gained_min,
        proc.feathers_gained_max,
        proc.random_threefold,
        proc.fan_three_uses,
    ) == expected
    assert proc.expected_feathers == expected[0] * 0.5
    assert proc.fan_trials == expected[1]
    assert proc.expected_threefold == expected[1] * 0.5
    assert proc.guaranteed_threefold == 19
    initial = {
        "Luuqu Iko": [(54, 27, 28, 45, 28, 17, 1, 1), (51, 25.5, 30, 48, 30, 18, 0, 1)],
        "Skye Uwu": [(57, 28.5, 30, 44, 27, 17, 3, 2), (51, 25.5, 31, 47, 29, 18, 3, 0)],
        "Felix Austed": [(58, 29, 31, 47, 30, 17, 2, 1), (53, 26.5, 23, 40, 23, 17, 1, 1)],
    }[player]
    for ready, values in zip(proc.ready_procs[:2], initial, strict=True):
        assert (
            sum(c for _, c in ready.trials),
            ready.expected,
            ready.random_grants,
            ready.uses,
            ready.random_consumed,
            ready.guaranteed_consumed,
            ready.expired,
            ready.remaining,
        ) == values
        assert ready.guaranteed_grants == 19
        assert ready.random_grants is not None
        assert ready.overlaps == ready.overwritten == ready.death_lost == 0
        assert ready.unknown_consumed == ready.unknown_removals == 0
        assert ready.random_grants + ready.guaranteed_grants == (
            ready.random_consumed + ready.guaranteed_consumed + ready.expired + ready.remaining
        )
    assert proc.full_use_expected_feathers == sum(v[1] + 19 for v in initial) * 0.5
    assert proc.full_use_expected_feathers is not None
    assert proc.full_use_expected_random_threefold == proc.full_use_expected_feathers * 0.5
    threefold = proc.ready_procs[2]
    assert threefold.random_consumed == expected[4]
    assert threefold.guaranteed_consumed == 19
    assert threefold.overwritten == threefold.expired == threefold.remaining == 0
    _print_analysis(result)
    output = capsys.readouterr().out
    assert "Technical Step:" in output and "Dance of the Dawn:" in output
    assert "Dances and personal buffs:\n  Devilment:" in output
    assert output.index("Devilment:") < output.index("Starfall Dance:") < output.index("Flourish:")
    assert "\n  Time    Steps" in output
    assert "\n\n  Time    Steps" not in output
    proc_section = output.split("Proc usage:", 1)[1].split("Esprit and Saber Dance:", 1)[0]
    assert proc_section.index("Effects active at fight end") < proc_section.index("Fan Dance IV:")
    assert "Dancer proc luck:" in output and "Proc usage:" in output
    assert "Initial GCD total" in output and "Symmetry" in output and "Flow" in output
    assert f"Feathers spent: {expected[1]}" in output
    assert "Starting feathers: 0 (fresh raid or trial pull)" in output
    assert proc.gcd_to_feather_chance == pytest.approx(0.25)
    assert "Ordinary GCD-to-Feather chain: 25%" in output
    assert "unknown origin" not in output and "Unexplained removals" not in output
    assert output.index("Gear:") < output.index("Food:") < output.index("Party main-stat bonus:")
    luck_section = output.split("Dancer proc luck:", 1)[1].split("\nPotions:", 1)[0]
    assert luck_section.index("Stage") < luck_section.index("Luck indices:") < luck_section.index("Feather luck score:")
    assert "Combined luck score:" not in output
    if player == "Skye Uwu":
        assert "GCD-to-Feather chain: 90.1/100" in output
        assert "Threefold: 76.2/100" in output
        assert proc.combined_feather_luck_min is not None
        assert output.count(f"Feather luck score: at least {proc.combined_feather_luck_min:.1f}/100") == 2
        assert "50 = baseline | 100 = every random roll succeeded" in output
        assert "90.1-100.0" not in output
        assert "Unlogged Feather overcap can increase the true score." in output
    assert proc.starting_feathers == (0,)
    assert "Unmatched landed damage:" not in output


def test_genuine_technical_finish_ghost_and_cache_round_trip(tmp_path, monkeypatch):
    from ffxiv_potency.analysis import analyze

    extract(tmp_path, CASES[0][0])
    actions = Path("data/jobs/dnc/7.4/actions.json")
    first = analyze_saved_fight(tmp_path, actions)
    assert dict(first.ghosted)["Quadruple Technical Finish"] == 1
    ghost = next(f for f in first.dnc_finishes if f.hits == 0)
    assert ghost.action == "Quadruple Technical Finish"
    assert ghost.seconds == pytest.approx(724.116)
    assert ghost.potency == 0

    def fail_recalculation(*args, **kwargs):
        raise AssertionError("unchanged Dancer analysis must reuse its typed cache")

    monkeypatch.setattr(analyze, "_analyze_saved_fight", fail_recalculation)
    assert analyze_saved_fight(tmp_path, actions) == first


ADDITIONAL_CASES = [
    (
        "9JkrhHjVnNLDtcXW/fight-8/source-9",
        ("Aria Tsuki", "savage_7_4", 521, 321, 4, 46, 92, 59, 59, 32),
        (0,),
    ),
    (
        "B31PfCgKktVjFWGv/fight-5/source-9",
        ("Lily Starblade", "savage_7_4", 519, 321, 4, 44, 96, 50, 50, 25),
        (0,),
    ),
    (
        "FxMDnymRV7CB3HGf/fight-6/source-14",
        ("Hildy Way", "relic_7_55", 506, 320, 3, 44, 90, 46, 46, 33),
        (0,),
    ),
    (
        "JHPG6py2dazxDnRC/fight-13/source-3",
        ("Sleepy Dazzle", "savage_7_4", 499, 322, 4, 46, 86, 48, 48, 26),
        (0,),
    ),
    (
        "ZJ3XNYGqmjWg8Bdw/fight-8/source-5",
        ("Ririna Lira", "relic_7_55", 513, 318, 4, 46, 84, 53, 53, 30),
        (0,),
    ),
    (
        "gmGXkyHxdqrYf9Dj/fight-45/source-204",
        ("Len Afflicted", "relic_7_55", 488, 315, 4, 46, 85, 45, 45, 20),
        (0,),
    ),
    (
        "k1Xbdcnv4ZMWxQG3/fight-9/source-66",
        ("Alma Spinel", "relic_7_55", 479, 324, 4, 46, 84, 34, 34, 19),
        (0,),
    ),
]


@pytest.mark.parametrize("prefix,expected,starting", ADDITIONAL_CASES)
def test_supplied_dancer_logs(tmp_path, audit_dnc, prefix, expected, starting):
    result = audit_dnc(tmp_path, "dnc_dancing_mad.zip", prefix, expected, starting)
    assert result.encounter_id == 1085


def test_tillana_during_downtime_is_a_valid_zero_damage_use(tmp_path):
    import json

    from ffxiv_potency.analysis import analyze as analyzer

    extract(tmp_path, CASES[1][0])
    actions = Path("data/jobs/dnc/7.4/actions.json")
    result = analyze_saved_fight(tmp_path, actions)
    # The utility use at the phase transition consumes its ready effect even
    # though no enemy was available for its damage.
    master = json.loads((tmp_path / "master-data.json").read_text())
    ability = next(a["gameID"] for a in master["abilities"] if a["name"] == "Tillana")
    casts = json.loads((tmp_path / "cast-events.json").read_text())
    assert next(a for a in result.actions if a.name == "Tillana").uses == 8
    assert result.execution is not None
    ready = next(r for r in result.execution.ready if r.name == "Tillana")
    assert ready.uses == ready.grants == sum(
        e.get("abilityGameID") == ability and not e.get("fake") for e in casts
    )
    assert "Tillana" not in dict(result.ghosted)
    assert analyzer.analyze_saved_fight(tmp_path, actions) == result
