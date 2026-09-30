"""Audit Bard DoT applications and Iron Jaws snapshots against a saved fight."""

import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from zipfile import ZipFile

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.auto_attacks import _summarize_auto_attacks
from ffxiv_potency.analysis.brd.buffs import brd_self_buff_windows
from ffxiv_potency.analysis.brd.dots import (
    brd_dot_potency,
    reconstruct_brd_dots,
    summarize_brd_dots,
)
from ffxiv_potency.analysis.profiles import _load_combat_profile


def test_iron_jaws_clipped_to_one_damage_contributes_one_percent_potency() -> None:
    event = {
        "type": "damage", "sourceID": 2, "targetID": 10,
        "timestamp": 1000, "packetID": 1, "abilityGameID": 77,
        "amount": 1, "overkill": 99,
    }
    summary = summarize_brd_dots(
        [], [event], [], {77: "Iron Jaws"}, {"Iron Jaws": {"potency": {"base": 100}}},
        2, potion_multiplier=1.08,
    )
    jaws = next(row for row in summary if row.name == "Iron Jaws")
    assert jaws.landed_uses == 1
    assert jaws.direct_potency == pytest.approx(1)


def test_zero_damage_overkill_refresh_retains_snapshot_for_later_tiny_tick() -> None:
    names = {1: "Stormbite", 2: "Iron Jaws"}
    events = [
        {"type": "damage", "sourceID": 2, "targetID": 10, "timestamp": 100,
         "packetID": 11, "abilityGameID": 1, "amount": 100, "buffs": "original."},
        {"type": "damage", "sourceID": 2, "targetID": 10, "timestamp": 200,
         "packetID": 12, "abilityGameID": 2, "amount": 0, "overkill": 200,
         "buffs": "refreshed."},
        {"type": "damage", "sourceID": 2, "targetID": 10, "timestamp": 300,
         "packetID": 12, "abilityGameID": 1, "amount": 1, "overkill": 99,
         "buffs": "refreshed.", "tick": True},
    ]
    tick, = reconstruct_brd_dots(events, names, 2)
    assert tick.matched and tick.snapshot_timestamp == 200
    assert tick.snapshot_buffs == "refreshed."
    assert tick.landed_fraction == pytest.approx(0.01)
    actions = {
        "Stormbite": {"potency": {"base": 100, "damage_over_time": {
            "potency_per_tick": 25,
        }}},
        "Iron Jaws": {"potency": {"base": 100}},
    }
    summary = summarize_brd_dots([], events, [], names, actions, 2, potion_multiplier=1.0)
    assert next(row for row in summary if row.name == "Iron Jaws").direct_potency == 0
    assert next(row for row in summary if row.name == "Stormbite").tick_potency == pytest.approx(0.25)

    events[1].pop("overkill")
    assert not reconstruct_brd_dots(events, names, 2)[0].matched


def test_dancing_mad_dot_snapshots() -> None:
    archive = Path(__file__).parents[1] / "fixtures/logs/brd_dancing_mad.zip"
    root = "7CANHrvwKT6tp2Gx/fight-7/source-2/"
    with ZipFile(archive) as saved:
        def load(name: str):
            return json.loads(saved.read(root + name + ".json"))

        names = {item["gameID"]: item["name"] for item in load("master-data")["abilities"]}
        ticks = reconstruct_brd_dots(load("damage-events"), names, 2)

    assert len(ticks) == 691  # Eight zero-damage ticks did not land.
    assert all(tick.matched for tick in ticks)
    assert all(tick.snapshot_buffs == tick.tick_buffs for tick in ticks)
    assert Counter((tick.name, tick.application_name) for tick in ticks) == {
        ("Caustic Bite", "Caustic Bite"): 62,
        ("Stormbite", "Stormbite"): 78,
        ("Caustic Bite", "Iron Jaws"): 282,
        ("Stormbite", "Iron Jaws"): 269,
    }
    # The target's DoTs were still ticking when refreshed 45.233 seconds
    # after the preceding Iron Jaws hit.
    assert all(tick.matched for tick in ticks if tick.application_packet == 36865)


def test_refresh_does_not_create_missing_dot_or_change_another_target() -> None:
    names = {1: "Stormbite", 2: "Caustic Bite", 3: "Iron Jaws"}

    def damage(time: int, packet: int, target: int, ability: int, buffs: str, **extra):
        return {
            "type": "damage", "timestamp": time, "packetID": packet,
            "sourceID": 2, "targetID": target, "abilityGameID": ability,
            "amount": 1, "buffs": buffs, **extra,
        }

    events = [
        damage(100, 10, 11, 1, "original."),
        damage(200, 11, 12, 1, "other."),
        damage(400, 20, 11, 3, "refreshed."),
        damage(3000, 20, 11, 1, "refreshed.", tick=True),
        damage(3000, 20, 11, 2, "refreshed.", tick=True),
        damage(3000, 11, 12, 1, "other.", tick=True),
    ]
    ticks = reconstruct_brd_dots(events, names, 2)
    assert [(tick.matched, tick.snapshot_buffs) for tick in ticks] == [
        (True, "refreshed."), (False, ""), (True, "other.")
    ]


def test_iron_jaws_refreshes_unexpired_dot_after_ticks_pause() -> None:
    names = {1: "Stormbite", 2: "Iron Jaws"}
    events = [
        {"type": "damage", "sourceID": 2, "targetID": 20, "timestamp": 1000,
         "packetID": 10, "abilityGameID": 1, "amount": 100, "buffs": "old."},
        {"type": "damage", "sourceID": 2, "targetID": 20, "timestamp": 4000,
         "packetID": 10, "abilityGameID": 1, "amount": 20, "tick": True},
        {"type": "damage", "sourceID": 2, "targetID": 20, "timestamp": 44000,
         "packetID": 20, "abilityGameID": 2, "amount": 100, "buffs": "new."},
        {"type": "damage", "sourceID": 2, "targetID": 20, "timestamp": 45000,
         "packetID": 20, "abilityGameID": 1, "amount": 20, "tick": True},
    ]
    ticks = reconstruct_brd_dots(events, names, 2)
    assert [(tick.matched, tick.snapshot_timestamp, tick.snapshot_buffs) for tick in ticks] == [
        (True, 1000, "old."), (True, 44000, "new."),
    ]

    events[2]["timestamp"] = 51000  # Past the old DoT's expiry and tick grace.
    events[3]["timestamp"] = 52000
    assert not reconstruct_brd_dots(events, names, 2)[-1].matched


def test_dancing_mad_dot_potency_retains_potion_after_it_expires() -> None:
    with ZipFile(Path(__file__).parents[1] / "fixtures/logs/brd_dancing_mad.zip") as saved:
        root = "7CANHrvwKT6tp2Gx/fight-7/source-2/"

        def load(name: str):
            return json.loads(saved.read(root + name + ".json"))

        names = {item["gameID"]: item["name"] for item in load("master-data")["abilities"]}
        buffs = load("buff-events")
        windows = brd_self_buff_windows(load("cast-events"), buffs, names, 2)
        ticks = reconstruct_brd_dots(load("damage-events"), names, 2)

    assert [round(window[2], 2) for window in windows[1002964]] == [
        1.02, 1.06, 1.06, 1.04, 1.06, 1.06, 1.06, 1.06, 1.06, 1.06
    ]
    prepull_raging = next(
        tick for tick in ticks
        if tick.name == "Caustic Bite" and tick.application_packet == 33039
    )
    assert brd_dot_potency(
        prepull_raging, 20, potion_multiplier=664 / 620, self_buff_windows=windows
    ) == pytest.approx(20 * 1.15 * 1.01 * 1.02)
    potion_falloffs = {
        event["timestamp"] for event in buffs
        if event.get("abilityGameID") == 1000049
        and event.get("targetID") == 2 and event.get("type") == "removebuff"
    }
    tick = next(
        tick for tick in ticks
        if "1000049." in tick.snapshot_buffs
        and any(tick.snapshot_timestamp < time < tick.timestamp for time in potion_falloffs)
    )
    assert tick.application_name == "Iron Jaws"
    # An independent test factor makes an expired potion visible in the result.
    potency = brd_dot_potency(
        tick, 20 if tick.name == "Caustic Bite" else 25,
        potion_multiplier=1.08, self_buff_windows=windows,
    )
    without_potion = brd_dot_potency(
        tick, 20 if tick.name == "Caustic Bite" else 25,
        potion_multiplier=1.0, self_buff_windows=windows,
    )
    assert math.isclose(potency / without_potion, 1.08)


def test_full_dancing_mad_analysis_uses_dot_snapshots_without_extra_potions(
    tmp_path: Path, extract_fight
) -> None:
    extract_fight("brd_dancing_mad.zip", "7CANHrvwKT6tp2Gx/fight-7/source-2/")
    actions = Path(__file__).parents[2] / "data/bard/7.55/actions.json"
    result = analyze_saved_fight(tmp_path, actions)
    dots = {row.name: row for row in result.brd_dots}
    full = {row.name: row for row in result.actions}

    assert result.potion.uses == 4
    assert result.hit_outcomes.known_hits == result.landed_damage_events - 691
    assert result.unmatched == ()
    assert (dots["Caustic Bite"].landed_uses, dots["Caustic Bite"].ticks) == (6, 344)
    assert (dots["Stormbite"].landed_uses, dots["Stormbite"].ticks) == (7, 347)
    assert (dots["Iron Jaws"].landed_uses, dots["Iron Jaws"].ticks) == (23, 0)
    assert dots["Caustic Bite"].total_potency == pytest.approx(8476.363042470388)
    assert dots["Stormbite"].total_potency == pytest.approx(10213.081034475488)
    for name in ("Caustic Bite", "Stormbite", "Iron Jaws"):
        assert full[name].potency_min == pytest.approx(dots[name].total_potency)
    assert full["Caustic Bite"].uses == 6
    assert full["Stormbite"].uses == 7
    encore = full["Radiant Encore"]
    assert sum(row.encore_hits for row in result.brd_finales) == encore.hits
    assert sum(row.encore_potency_min for row in result.brd_finales) == pytest.approx(
        encore.potency_min
    )
    assert next(row for row in result.brd_finales if row.encore_hits == 2).coda == 3

    apex = next(row for row in result.brd_potency_estimates if row.action == "Apex Arrow")
    assert len(apex.apex_uses) == 18
    assert all(use.plausible_gauges for use in apex.apex_uses)
    assert all(use.gauge in use.plausible_gauges for use in apex.apex_uses)

    # Compare ordinary, unbuffed hits directly; this checks the auto-attack
    # convention against action damage without fitting to the implementation.
    events = json.loads((tmp_path / "damage-events.json").read_text(encoding="utf-8"))
    master = json.loads((tmp_path / "master-data.json").read_text(encoding="utf-8"))
    names = {ability["gameID"]: ability["name"] for ability in master["abilities"]}
    normal = {"Shot": [], "Burst Shot": []}
    for event in events:
        name = names.get(event.get("abilityGameID"))
        if (name in normal and event.get("type") == "damage"
                and event.get("sourceID") == 2 and event.get("hitType") == 1
                and not event.get("directHit") and event.get("multiplier", 1) == 1
                and not event.get("overkill")):
            normal[name].append(event["amount"])
    observed_shot_potency = median(normal["Shot"]) / (median(normal["Burst Shot"]) / 220)
    assert observed_shot_potency == pytest.approx(result.auto_attacks[0].potency_per_hit, abs=2)


def test_clipped_auto_attack_counts_only_landed_fraction_without_self_buffs() -> None:
    shots = [
        {"_resolved_name": "Shot", "timestamp": 0, "amount": 100},
        {"_resolved_name": "Shot", "timestamp": 3040, "amount": 1, "overkill": 99},
    ]
    summary, _, _ = _summarize_auto_attacks(shots, "bard", _load_combat_profile("bard"))

    assert summary[0].hits == 2
    assert summary[0].total_potency == pytest.approx(summary[0].potency_per_hit * 1.01)


def test_armys_paeon_and_muse_shots_do_not_set_weapon_delay() -> None:
    # Faster Shots still contribute potency, but cannot estimate base delay.
    shots = [
        {"_resolved_name": "Shot", "timestamp": timestamp, "buffs": buff}
        for timestamp, buff in (
            (0, ""), (3040, ""), (6080, ""),
            (8500, "1002218."), (10920, "1002218."),
            (13340, "1001932."), (15760, "1001932."),
            (18800, ""), (21840, ""),
        )
    ]
    summary, _, _ = _summarize_auto_attacks(shots, "bard", _load_combat_profile("bard"))
    assert summary[0].hits == 9
    assert summary[0].estimated_delay_seconds == pytest.approx(3.04)
    assert summary[0].weapon_delay_seconds == 3.04


def test_prepull_raging_strikes_snapshot_is_counted() -> None:
    windows = brd_self_buff_windows(
        [],
        [{"timestamp": 30_000, "type": "removebuff", "sourceID": 2,
          "targetID": 2, "abilityGameID": 1000125}],
        {1000125: "Raging Strikes"}, 2,
    )
    assert windows[1000125] == ((10_000, 30_000, 1.15),)
