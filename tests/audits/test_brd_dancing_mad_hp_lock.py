"""A zero-damage Iron Jaws refresh during Exdeath's HP lock."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.brd.dots import reconstruct_brd_dots


def test_iron_jaws_zero_direct_hit_refreshes_one_landed_stormbite_tick(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight(
        "brd_dancing_mad_hp_lock_refresh.zip", "rDXkG89Af2z7Y3xv/fight-24/source-490/",
    )
    fight = json.loads((tmp_path / "fight.json").read_text(encoding="utf-8"))
    master = json.loads((tmp_path / "master-data.json").read_text(encoding="utf-8"))
    damage = json.loads((tmp_path / "damage-events.json").read_text(encoding="utf-8"))
    names = {entry["gameID"]: entry["name"] for entry in master["abilities"]}
    refresh = next(event for event in damage if event.get("type") == "damage"
                   and event.get("packetID") == 80087 and names[event["abilityGameID"]] == "Iron Jaws")
    assert (refresh["amount"], refresh["overkill"], refresh["targetID"]) == (0, 10264, 508)
    ticks = reconstruct_brd_dots(damage, names, 490)
    tiny_tick = next(tick for tick in ticks if tick.application_packet == 80087)
    assert tiny_tick.matched
    assert tiny_tick.application_name == "Iron Jaws"
    assert tiny_tick.snapshot_timestamp == refresh["timestamp"]
    assert tiny_tick.snapshot_buffs == "1002218."
    assert tiny_tick.timestamp - fight["startTime"] == 703625
    assert tiny_tick.landed_fraction == pytest.approx(1 / 3443)
    assert all(tick.matched for tick in ticks)

    result = analyze_saved_fight(tmp_path, Path("data/bard/7.55/actions.json"))
    assert result.unmatched == ()
    assert next(row for row in result.brd_dots if row.name == "Stormbite").ticks == 345
    assert any(hit.action == "Stormbite" and hit.damage == 1 and hit.overkill == 3442
               for hit in result.reduced_damage_hits)
