"""Multi-target Bard regression from Vamp Fatale, report Kn9vkBgZT3RPGxDf."""

import json
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import analyze_saved_fight


def test_brd_adds_and_clipped_hit(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight("brd_vamp_fatale.zip", "Kn9vkBgZT3RPGxDf/fight-21/source-4/")
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    result = analyze_saved_fight(tmp_path, actions)
    by_name = {action.name: action for action in result.actions}

    assert result.fight_name == "Vamp Fatale"
    assert result.unmatched == ()
    assert (by_name["Shadowbite"].uses, by_name["Shadowbite"].hits) == (5, 13)
    assert by_name["Shadowbite"].potency_min == pytest.approx(2604)
    assert (by_name["Rain of Death"].uses, by_name["Rain of Death"].hits) == (9, 28)
    apex = next(row for row in result.brd_potency_estimates if row.action == "Apex Arrow")
    assert (len(apex.apex_uses), apex.estimated_hits) == (8, 11)
    assert all(use.potency is not None for use in apex.apex_uses)
    assert sum(use.potency for use in apex.apex_uses if use.potency is not None) == pytest.approx(
        by_name["Apex Arrow"].potency_min
    )
    assert dict(result.brd_song_durations)["Army's Paeon"] == pytest.approx(36.97225)
    assert result.reduced_damage_hits[0].target == "Charnel Cell"
    assert result.reduced_damage_hits[0].damage == 19_726
    assert result.reduced_damage_hits[0].overkill == 16_795

    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert "Burst Shot on Charnel Cell: 19,726/36,521 damage" in output
    assert "Burst Shot on Coffinmaker" in output
    assert "01m03s: 1 hit, best estimate 80 gauge (plausible 80–85 gauge), 566 total potency" in output
    assert "Army's Paeon: 4 uses, 37.0s average duration" in output
    assert "Heartbreak Shot on Charnel Cell (target defeated before hit landed)" in output
    assert "Burst Shot on Coffinmaker (" not in output  # Its target HP was not recorded.
    assert "phase transition" not in output


def test_brd_echo_normalization_matches_unboosted_fight(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight("brd_vamp_fatale.zip", "Kn9vkBgZT3RPGxDf/fight-21/source-4/")
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    ordinary = analyze_saved_fight(tmp_path, actions)

    damage_path = tmp_path / "damage-events.json"
    damage = json.loads(damage_path.read_text(encoding="utf-8"))
    for event in damage:
        if event.get("type") in {"damage", "calculateddamage"}:
            for field in ("amount", "unmitigatedAmount", "overkill"):
                if isinstance(event.get(field), (int, float)):
                    event[field] *= 1.12
    damage_path.write_text(json.dumps(damage), encoding="utf-8")
    (tmp_path / "combatant-info-events.json").write_text(
        json.dumps([{"sourceID": 4, "auras": [{"ability": 1000042}]}]), encoding="utf-8",
    )
    rankings_path = tmp_path / "rankings.json"
    if rankings_path.is_file():
        rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
        for value in (rankings.get("rankings"), rankings.get("rdps")):
            if isinstance(value, dict):
                for row in value.get("data", []):
                    row["partition"] = 13
        rankings_path.write_text(json.dumps(rankings), encoding="utf-8")

    echoed = analyze_saved_fight(tmp_path, actions)
    assert echoed.echo_status == "observed"
    assert echoed.potency_min == pytest.approx(ordinary.potency_min)
    assert echoed.potency_max == pytest.approx(ordinary.potency_max)
    assert echoed.brd_potency_estimates == ordinary.brd_potency_estimates
    assert echoed.reduced_damage_hits[0].damage == pytest.approx(
        ordinary.reduced_damage_hits[0].damage
    )
    assert (echoed.rdps, echoed.ndps) == (ordinary.rdps, ordinary.ndps)


def test_barrage_shadowbite_buffs_every_target(
    tmp_path: Path, extract_fight
) -> None:
    extract_fight("brd_vamp_fatale.zip", "Kn9vkBgZT3RPGxDf/fight-21/source-4/")
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    ordinary = analyze_saved_fight(tmp_path, actions)
    ordinary_potency = next(row.potency_min for row in ordinary.actions if row.name == "Shadowbite")

    casts = json.loads((tmp_path / "cast-events.json").read_text(encoding="utf-8"))
    first_shadowbite = next(cast for cast in casts if cast.get("packetID") == 25250)
    timestamp = first_shadowbite["timestamp"]
    buffs_path = tmp_path / "buff-events.json"
    buffs = json.loads(buffs_path.read_text(encoding="utf-8"))
    buffs.extend([
        {"type": "applybuff", "timestamp": timestamp - 1000,
         "sourceID": 4, "targetID": 4, "abilityGameID": 1000128, "duration": 10000},
        {"type": "removebuff", "timestamp": timestamp,
         "sourceID": 4, "targetID": 4, "abilityGameID": 1000128},
    ])
    buffs_path.write_text(json.dumps(buffs), encoding="utf-8")

    buffed = analyze_saved_fight(tmp_path, actions)
    buffed_potency = next(row.potency_min for row in buffed.actions if row.name == "Shadowbite")
    # Army's Paeon adds 1% damage to both target hits in this packet.
    assert buffed_potency == pytest.approx(ordinary_potency + 2 * 100 * 1.01)


def test_recorded_targetability_explains_ghosted_burst_shot(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight("brd_vamp_fatale.zip", "Kn9vkBgZT3RPGxDf/fight-21/source-4/")
    (tmp_path / "targetability-events.json").write_text(json.dumps([
        {"type": "targetabilityupdate", "timestamp": 5768288,
         "sourceID": 5, "targetID": 5, "targetable": 0},
        {"type": "targetabilityupdate", "timestamp": 5768511,
         "sourceID": 20, "targetID": 20, "targetable": 1},
        {"type": "targetabilityupdate", "timestamp": 5819947,
         "sourceID": 5, "targetID": 5, "targetable": 1},
    ]), encoding="utf-8")
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    cli._print_analysis(analyze_saved_fight(tmp_path, actions))
    output = capsys.readouterr().out
    assert "Burst Shot on Vamp Fatale (target became untargetable before hit landed)" in output
    assert "Burst Shot on Coffinmaker (target became untargetable" not in output


def test_other_players_overkill_explains_ghosted_coffinmaker_shot(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight("brd_vamp_fatale.zip", "Kn9vkBgZT3RPGxDf/fight-21/source-4/")
    casts = json.loads((tmp_path / "cast-events.json").read_text(encoding="utf-8"))
    coffin_id = next(cast["targetID"] for cast in casts if cast.get("timestamp") == 5818473)
    (tmp_path / "encounter-overkill-events.json").write_text(json.dumps([
        {"type": "damage", "timestamp": 5819053, "sourceID": 8,
         "targetID": coffin_id, "packetID": 99999,
         "amount": 30315, "overkill": 18059},
    ]), encoding="utf-8")
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    cli._print_analysis(analyze_saved_fight(tmp_path, actions))
    assert "Burst Shot on Coffinmaker (target defeated before hit landed)" in capsys.readouterr().out


def test_repeated_cell_overkill_is_not_a_boss_hp_lock(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight("brd_vamp_fatale.zip", "Kn9vkBgZT3RPGxDf/fight-21/source-4/")
    # Another player keeps dealing overkill to a cell after this Bard's cast.
    (tmp_path / "encounter-overkill-events.json").write_text(json.dumps([
        {"type": "damage", "timestamp": timestamp, "sourceID": 8,
         "targetID": 30, "packetID": 99999 + index,
         "amount": 0, "overkill": 1000}
        for index, timestamp in enumerate((6143000, 6146000, 6149000))
    ]), encoding="utf-8")
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    cli._print_analysis(analyze_saved_fight(tmp_path, actions))
    output = capsys.readouterr().out
    assert "Heartbreak Shot on Charnel Cell (phase HP lock" not in output


def test_rank_two_cell_dies_from_own_sidewinder_before_burst_shot_lands(
    tmp_path: Path, extract_fight, capsys: pytest.CaptureFixture[str]
) -> None:
    extract_fight(
        "brd_vamp_fatale_rank2.zip", "xCN3zZp6rnDwTMLq/fight-10/source-325/"
    )
    actions = Path(__file__).resolve().parents[2] / "data/bard/7.55/actions.json"
    result = analyze_saved_fight(tmp_path, actions)
    assert result.unmatched == ()

    casts = json.loads((tmp_path / "cast-events.json").read_text(encoding="utf-8"))
    overkills = json.loads(
        (tmp_path / "encounter-overkill-events.json").read_text(encoding="utf-8")
    )
    burst = next(event for event in casts if event.get("packetID") == 109150)
    killing_hit = next(event for event in overkills if event.get("packetID") == 109155)
    assert burst["sourceID"] == killing_hit["sourceID"] == 325
    assert burst["targetID"] == killing_hit["targetID"] == 298
    assert burst["timestamp"] < killing_hit["timestamp"]
    assert killing_hit["amount"] == 39053
    assert killing_hit["overkill"] == 10293

    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert "07m15s Burst Shot on Charnel Cell (target defeated before hit landed)" in output
    assert "Burst Shot on Charnel Cell (phase HP lock" not in output
