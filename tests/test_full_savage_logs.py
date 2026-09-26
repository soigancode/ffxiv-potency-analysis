"""End-to-end MCH regression across five saved patch-7.55 savage fights."""

from pathlib import Path

import pytest

from ffxiv_potency.fflogs import analyze_saved_fight


@pytest.mark.parametrize(
    ("archive_name", "prefix", "encounter", "landed", "autos", "queens", "potions"),
    [
        ("vamp_fatale_full.zip", "DFm9brj421X6T73k/fight-1/source-2/", 101, 626, 186, 12, 2),
        ("red_hot_deep_blue_full.zip", "R86rXnMqjHTDJz3A/fight-4/source-11/", 102, 695, 197, 11, 2),
        ("tyrant_full.zip", "zYLAW7KTBk8P4XxG/fight-9/source-18/", 103, 771, 243, 14, 3),
        ("lindwurm_full.zip", "kmCB1yh4GDxYJMtf/fight-24/source-1107/", 104, 480, 147, 10, 2),
        ("lindwurm_full.zip", "BrmtPJ2XfaY6kGTC/fight-7/source-559/", 105, 632, 201, 10, 2),
    ],
)
def test_full_savage_log_coverage(
    tmp_path: Path,
    machinist_actions: Path,
    extract_fight,
    archive_name: str,
    prefix: str,
    encounter: int,
    landed: int,
    autos: int,
    queens: int,
    potions: int,
) -> None:
    extract_fight(archive_name, prefix)
    result = analyze_saved_fight(tmp_path, machinist_actions)

    assert result.encounter_id == encounter
    assert result.landed_damage_events == landed
    assert result.matched_damage_events + sum(auto.hits for auto in result.auto_attacks) == landed
    assert sum(auto.hits for auto in result.auto_attacks) == autos
    assert len(result.pet_deployments) == queens
    assert result.potion.uses == potions
    assert result.unmatched == ()
    assert 0 <= result.adjusted_luck_score <= result.luck_score <= 1

    by_name = {action.name: action for action in result.actions}
    if encounter == 101:
        assert (by_name["Chain Saw"].uses, by_name["Chain Saw"].hits) == (9, 10)
        assert (by_name["Scattergun"].uses, by_name["Scattergun"].hits) == (1, 3)
    if encounter == 102:
        assert (by_name["Chain Saw"].uses, by_name["Chain Saw"].hits) == (9, 15)
        assert (by_name["Flamethrower"].uses, by_name["Flamethrower"].hits) == (2, 14)
    if encounter == 104:
        assert result.pet_deployments[-1].missing_finishers == ("Crowned Collider",)
