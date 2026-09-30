"""Hand-audited slice of FF Logs zYLAW7KTBk8P4XxG, fight 9, source 18.

Five landed Blazing Shots during Hypercharge: 5 * (240 + 20) potency.
Five weaponskill triggers before Wildfire resolves: 5 * 240 potency.
Six consecutive auto-attacks match a 2.64s weapon delay: their comparable
potency is 80 * 183 / 208 / 1.2 each; the last four carry Medicated. All five Blazing Shots and
Wildfire carry Medicated too. Player potion factor: 3837 / 3546.
"""

import json
from pathlib import Path
from statistics import median

import pytest

from ffxiv_potency.analysis import analyze_saved_fight


def test_audited_wildfire_hypercharge_auto_attacks_and_three_potions(
    tmp_path: Path, mch_actions: Path, load_audit
) -> None:
    load_audit("mch_tyrant_audit.json")
    result = analyze_saved_fight(tmp_path, mch_actions)
    by_name = {action.name: action for action in result.actions}

    blazing = by_name["Blazing Shot"]
    wildfire = by_name["Wildfire"]
    assert (blazing.uses, blazing.hits) == (5, 5)
    assert blazing.potency_min == blazing.potency_max == pytest.approx(5 * (240 + 20) * 3837 / 3546)
    assert (wildfire.uses, wildfire.hits) == (1, 1)
    assert wildfire.potency_min == wildfire.potency_max == pytest.approx(5 * 240 * 3837 / 3546)

    (shot,) = result.auto_attacks
    assert shot.hits == 6
    assert shot.weapon_delay_seconds == pytest.approx(2.64)
    comparable_shot = 80 * 183 / 208 / 1.2
    assert shot.potency_per_hit == pytest.approx(comparable_shot)
    assert shot.total_potency == pytest.approx(
        6 * comparable_shot + 4 * comparable_shot * (3837 / 3546 - 1)
    )

    assert result.potion.uses == 3
    assert [window.start_seconds for window in result.potion.windows] == pytest.approx(
        [3.968, 291.713, 596.305]
    )
    assert result.potion.potted_potency_min == pytest.approx(
        5 * 260 + 5 * 240 + 4 * comparable_shot
    )
    assert result.potion.gained_potency_min == pytest.approx(
        (5 * 260 + 5 * 240 + 4 * comparable_shot) * (3837 / 3546 - 1)
    )
    assert result.ghosted == ()
    assert result.unmatched == ()
    assert len(result.mch_wildfires) == 1
    wildfire_use = result.mch_wildfires[0]
    assert wildfire_use.applied_seconds == pytest.approx(14.091)
    assert wildfire_use.detonated_seconds == pytest.approx(24.673)
    assert wildfire_use.landed_weaponskills == 5
    assert wildfire_use.potency == pytest.approx(wildfire.potency_min)


@pytest.mark.parametrize(
    ("potion_time", "expected_potted"),
    [(16939728, True), (16966728, False)],
)
def test_wildfire_potion_snapshots_on_application(
    tmp_path: Path, mch_actions: Path, load_audit, potion_time: int, expected_potted: bool
) -> None:
    source = load_audit("mch_tyrant_audit.json")
    casts = source["cast_events"]
    potion_cast = next(cast for cast in casts if cast["abilityGameID"] == 34603667)
    potion_cast["timestamp"] = potion_time
    (tmp_path / "cast-events.json").write_text(json.dumps(casts), encoding="utf-8")
    damage = source["damage_events"]
    explosion = next(event for event in damage if event["abilityGameID"] == 1000861)
    explosion["buffs"] = "" if expected_potted else "1000049."
    (tmp_path / "damage-events.json").write_text(json.dumps(damage), encoding="utf-8")

    result = analyze_saved_fight(tmp_path, mch_actions)
    expected = 1200 * (3837 / 3546 if expected_potted else 1)
    assert result.mch_wildfires[0].potency == pytest.approx(expected)
    assert next(
        action for action in result.actions if action.name == "Wildfire"
    ).potency_min == pytest.approx(expected)


def test_wildfire_without_detonation_is_visible(
    tmp_path: Path, mch_actions: Path, load_audit
) -> None:
    source = load_audit("mch_tyrant_audit.json")
    damage = [event for event in source["damage_events"] if event["abilityGameID"] != 1000861]
    (tmp_path / "damage-events.json").write_text(json.dumps(damage), encoding="utf-8")

    (wildfire,) = analyze_saved_fight(tmp_path, mch_actions).mch_wildfires
    assert wildfire.detonated_seconds is None
    # Without an observed detonation or removal, the nominal 10s window
    # excludes the final hit that landed after that window.
    assert wildfire.landed_weaponskills == 4
    assert wildfire.potency == 0


def test_wildfire_recovers_prepull_potion_when_cast_is_missing(
    tmp_path: Path, mch_actions: Path, load_audit
) -> None:
    source = load_audit("mch_tyrant_audit.json")
    casts = [
        cast
        for cast in source["cast_events"]
        if cast["abilityGameID"] != 34603667 or cast["timestamp"] != 16953696
    ]
    (tmp_path / "cast-events.json").write_text(json.dumps(casts), encoding="utf-8")

    result = analyze_saved_fight(tmp_path, mch_actions)
    assert result.mch_wildfires[0].potency == pytest.approx(1200 * 3837 / 3546)


def test_detonator_marks_early_wildfire_without_changing_potency(
    tmp_path: Path, mch_actions: Path, load_audit, capsys
) -> None:
    source = load_audit("mch_tyrant_audit.json")
    source["master_data"]["abilities"].append({"gameID": 9001, "name": "Detonator"})
    source["cast_events"].append(
        {
            "timestamp": 16973500,
            "type": "cast",
            "packetID": 9999,
            "sourceID": 18,
            "targetID": 60,
            "abilityGameID": 9001,
        }
    )
    (tmp_path / "master-data.json").write_text(json.dumps(source["master_data"]), encoding="utf-8")
    (tmp_path / "cast-events.json").write_text(json.dumps(source["cast_events"]), encoding="utf-8")

    result = analyze_saved_fight(tmp_path, mch_actions)
    assert result.mch_wildfires[0].detonated_early
    assert result.mch_wildfires[0].potency == pytest.approx(1200 * 3837 / 3546)
    from ffxiv_potency import cli

    cli._print_analysis(result)
    assert "potency (detonated early)" in capsys.readouterr().out


def test_mch_tyrant_shot_timing_matches_damage_reference(
    tmp_path: Path, mch_actions: Path, extract_fight,
) -> None:
    """Report aDfQWqPzcZAmYNFx has 2.64s and 2.68s Shot clusters."""
    extract_fight(
        "mch_tyrant_auto_attack_timing.zip",
        "aDfQWqPzcZAmYNFx/fight-2/source-7/",
    )
    result = analyze_saved_fight(tmp_path, mch_actions)
    (shot,) = result.auto_attacks
    assert shot.hits == 233
    assert shot.estimated_delay_seconds == pytest.approx(2.682)
    assert shot.weapon_delay_seconds == 2.64

    # Independent damage comparison: ordinary unbuffed Shots against the
    # known 220-potency Heated Split Shot, excluding Crit, DH and overkill.
    events = json.loads((tmp_path / "damage-events.json").read_text())
    normal = {8: [], 7411: []}
    for event in events:
        ability = event.get("abilityGameID")
        if (ability in normal and event.get("type") == "calculateddamage"
                and event.get("sourceID") == 7 and event.get("hitType") == 1
                and not event.get("directHit") and event.get("multiplier", 1) == 1
                and not event.get("buffs") and not event.get("overkill")):
            normal[ability].append(event["amount"])
    assert (len(normal[8]), len(normal[7411])) == (69, 16)
    observed_potency = median(normal[8]) / median(normal[7411]) * 220
    assert observed_potency == pytest.approx(58.84, abs=0.01)
    assert shot.potency_per_hit == pytest.approx(observed_potency, abs=1)
