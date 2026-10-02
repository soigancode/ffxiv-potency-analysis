"""Independent WAR potency and luck arithmetic using the supplied log packets."""

import json
from collections import defaultdict
from math import floor
from pathlib import Path
from statistics import mean
from zipfile import ZipFile

import pytest

from ffxiv_potency.analysis import analyze_saved_fight

BASE = {
    "Heavy Swing": 240,
    "Maim": 190,
    "Storm's Path": 220,
    "Storm's Eye": 220,
    "Overpower": 110,
    "Mythril Tempest": 100,
    "Tomahawk": 150,
    "Fell Cleave": 580,
    "Decimate": 180,
    "Inner Chaos": 700,
    "Chaotic Cyclone": 200,
    "Onslaught": 150,
    "Upheaval": 420,
    "Orogeny": 150,
    "Damnation": 55,
    "Primal Rend": 720,
    "Primal Ruination": 800,
    "Primal Wrath": 700,
}
COMBO = {"Maim": 340, "Storm's Path": 500, "Storm's Eye": 500, "Mythril Tempest": 140}
FALLOFF = {"Primal Rend", "Primal Ruination", "Primal Wrath"}
FORCED = {"Inner Chaos", "Chaotic Cyclone", "Primal Rend", "Primal Ruination"}


@pytest.fixture
def audit_war():
    return _audit_war


def _audit_war(tmp_path, archive, prefix, expected):
    with ZipFile(Path("tests/fixtures/logs") / archive) as logs:
        for member in logs.namelist():
            if member.startswith(prefix + "/") and member.endswith(".json"):
                (tmp_path / Path(member).name).write_bytes(logs.read(member))

    def read(name):
        return json.loads((tmp_path / name).read_text())

    master = read("master-data.json")
    damage, casts, buffs = (
        read("damage-events.json"),
        read("cast-events.json"),
        read("buff-events.json"),
    )
    source = int(prefix.rsplit("source-", 1)[1])
    names = {action["gameID"]: action["name"] for action in master["abilities"]}
    result = analyze_saved_fight(tmp_path, Path("data/jobs/war/7.5/actions.json"), use_cache=False)
    _player, encounter, since, _gear, party = expected
    assert (
        result.source_name,
        result.encounter_id,
        result.actions_since,
        result.gear_id,
        result.party_bonus_percent,
    ) == expected
    assert result.unmatched == ()
    assert "Damnation" not in dict(result.ghosted)
    assert result.potency_min == result.potency_max
    assert result.auto_attacks[0].weapon_delay_seconds == 3.36
    assert result.auto_attacks[0].potency_per_hit == pytest.approx(90 * 228 / 204)
    assert result.potion.item is not None
    assert result.potion.item.name == "Grade 4 Gemdraught of Strength [HQ]"

    base = dict(BASE)
    if since == "7.4":
        base.update({"Inner Chaos": 660, "Primal Rend": 700, "Primal Ruination": 780})
    strength = 6472 * (100 + party) // 100
    main = lambda stat: 100 + 190 * (stat - 440) // 440
    potion = main(strength + 541) / main(strength)
    critical_stat = 3595
    critical_bonus = lambda stat: (400 + 200 * (stat - 420) // 2780) / 1000
    critical_chance = lambda stat: (50 + 200 * (stat - 420) // 2780) / 1000
    direct_chance = 550 * (1230 - 420) // 2780 / 1000
    packets = defaultdict(list)
    for event in damage:
        if event["type"] == "damage" and event.get("amount", 0) > 0 and event.get("hitType") != 10:
            packets[event["packetID"], event["abilityGameID"]].append(event)
    times = {
        (event["packetID"], event["abilityGameID"]): event["timestamp"]
        for event in damage
        if event["type"] == "calculateddamage"
    }
    times.update(
        {(event["packetID"], event["abilityGameID"]): event["timestamp"] for event in casts}
    )
    tempest = [
        event
        for event in buffs
        if event.get("targetID") == source
        and event.get("sourceID") == source
        and event.get("abilityGameID") == 1002677
    ]
    food_changes = [
        event
        for event in buffs
        if event.get("targetID") == source and event.get("abilityGameID") == 1000048
    ]
    initial = next(
        event for event in read("combatant-info-events.json") if event["sourceID"] == source
    )
    initially_fed = any(aura.get("ability") == 1000048 for aura in initial["auras"])
    totals = defaultdict(float)
    auto = potted = gain = luck = maximum = adjustment = baseline = 0.0
    eligible = guaranteed = 0
    hb_weight = hb_bonus = hb_adjustment = 0.0
    observed = defaultdict(list)
    for hits in packets.values():
        primary = max(
            hits,
            key=lambda hit: (
                (hit["amount"] + max(0, hit.get("overkill", 0)))
                / (1 + critical_bonus(critical_stat) if hit["hitType"] == 2 else 1)
                / (1.25 if hit.get("directHit") else 1)
                / hit.get("multiplier", 1)
            ),
        )
        for hit in hits:
            name = names[hit["abilityGameID"]]
            statuses = {int(s) for s in str(hit.get("buffs", "")).split(".") if s.isdigit()}
            time = times[hit["packetID"], hit["abilityGameID"]]
            if name in {"Storm's Eye", "Mythril Tempest"}:
                time -= 0.001
            previous = [event for event in tempest if event["timestamp"] <= time]
            last = max(previous, key=lambda event: event["timestamp"], default=None)
            surge = 1.0
            if 1002677 in statuses and (
                last is None
                or last["type"] in {"applybuff", "refreshbuff"}
                and time < last["timestamp"] + last["duration"]
            ):
                surge = 1.1
            value = 90 * 228 / 204 if name == "Attack" else base[name]
            if hit.get("bonusPercent", 0) > 0:
                value = COMBO.get(name, value)
            if name in FALLOFF and hit is not primary:
                value *= 0.5
            value *= surge * hit["amount"] / (hit["amount"] + max(0, hit.get("overkill", 0)))
            if 1002911 in statuses:
                assert encounter == 4550
                value *= 0.85
            assert not statuses & {1000043, 1000044}, (
                "add an independent revival check for this log"
            )
            if 1000049 in statuses:
                potted += value
                gain += value * (potion - 1)
                value *= potion
            if name == "Attack":
                auto += value
            else:
                totals[name] += value
            eligible += 1
            preceding_food = [
                event for event in food_changes if event["timestamp"] <= hit["timestamp"]
            ]
            food = max(preceding_food, key=lambda event: event["timestamp"], default=None)
            fed = food["type"] != "removebuff" if food else initially_fed
            stat = critical_stat if fed else critical_stat - 91
            rate, bonus = critical_chance(stat), critical_bonus(stat)
            outcome = (1 + bonus if hit["hitType"] == 2 else 1) * (
                1.25 if hit.get("directHit") else 1
            )
            crit_extra = (0.10 if 1001221 in statuses else 0) + (0.10 if 1000786 in statuses else 0)
            crit_extra += 0.20 if 1001825 in statuses else 0
            crit_extra += 0.02 if statuses & {1002216, 1002009} else 0
            dh_extra = (0.20 if 1000141 in statuses else 0) + (0.03 if 1002218 in statuses else 0)
            dh_extra += 0.20 if 1001825 in statuses else 0
            hb_weight += value
            if name in FORCED or name in {"Fell Cleave", "Decimate"} and 1001177 in statuses:
                assert hit["hitType"] == 2 and hit.get("directHit") is True
                guaranteed += 1
                det_stat = 3146 if _gear == "relic_7_55" else 3066
                if not fed:
                    det_stat -= 151
                det_factor = (1000 + 140 * (det_stat - 440) // 2780) / 1000
                direct_factor = (det_factor + 0.040) / det_factor
                extra = (
                    (1 + bonus)
                    * 1.25
                    * direct_factor
                    * (
                        (floor((1 + crit_extra * bonus) * 1000 + 1e-9) / 1000)
                        * (floor((1 + dh_extra * 0.25) * 1000 + 1e-9) / 1000)
                        - 1
                    )
                )
                hb_bonus += value * (outcome * direct_factor - 1 + extra)
                hb_adjustment += value * extra
                eligible -= 1
                continue
            before = (1 + rate * bonus) * (1 + direct_chance * 0.25)
            after = (1 + min(1, rate + crit_extra) * bonus) * (
                1 + min(1, direct_chance + dh_extra) * 0.25
            )
            luck += value * (outcome - 1)
            maximum += value * ((1 + bonus) * 1.25 - 1)
            adjustment += value * (after - before)
            baseline += value * (before - 1)
            hb_bonus += value * (outcome - 1)
            hb_adjustment += value * (after - before)
            if (
                name in {"Attack", "Heavy Swing"}
                and hit["hitType"] == 1
                and not hit.get("directHit")
            ):
                observed[name].append(
                    (hit["amount"] + max(0, hit.get("overkill", 0))) / hit.get("multiplier", 1)
                )
    assert {a.name for a in result.actions} == set(totals)
    for action in result.actions:
        assert action.potency_min == pytest.approx(totals[action.name]), action.name
    assert result.auto_attacks[0].total_potency == pytest.approx(auto)
    assert result.potency_min == pytest.approx(sum(totals.values()) + auto)
    assert result.potion.potted_potency_min == pytest.approx(potted)
    assert result.potion.gained_potency_min == pytest.approx(gain)
    assert result.luck_score == pytest.approx(luck / maximum)
    assert result.adjusted_luck_score == pytest.approx(
        max(0, min(1, (luck - adjustment) / maximum))
    )
    assert result.luck_baseline == pytest.approx(baseline / maximum)
    assert result.hit_bonus == pytest.approx(hb_bonus / hb_weight)
    assert result.adjusted_hit_bonus == pytest.approx(
        max(0, (hb_bonus - hb_adjustment) / hb_weight)
    )
    assert guaranteed > 0 and eligible > 0
    assert mean(observed["Attack"]) / mean(
        observed["Heavy Swing"]
    ) * 240 * 204 / 228 == pytest.approx(90, abs=2)
    return result
