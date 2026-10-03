"""Potency-changing snapshot boundaries and delayed spell enhancement expiry."""

import json
from pathlib import Path

import pytest
from test_pld_state import buff

from ffxiv_potency.analysis import analyze_saved_fight


def saved_pld(tmp_path, casts, damage, buffs=(), end=40000, life=()):
    names = {1: "Holy Spirit", 2: "Confiteor", 3: "Blade of Faith", 4: "Blade of Truth",
             5: "Blade of Valor", 6: "Imperator", 9: "Circle of Scorn", 10: "Fast Blade",
             11: "Fight or Flight", 1000248: "Circle of Scorn"}
    data = {"fight": {"id": 1, "encounterID": 101, "name": "Vamp Fatale", "startTime": 0,
                      "endTime": end, "playedPatch": "7.56", "friendlyPlayers": [1]},
            "master-data": {"abilities": [{"gameID": k, "name": n} for k, n in names.items()],
                            "actors": [{"id": 1, "name": "Test PLD", "type": "Player", "subType": "Paladin"}]},
            "cast-events": casts, "damage-events": damage, "buff-events": list(buffs),
            "life-events": list(life)}
    for name, value in data.items():
        (tmp_path / (name + ".json")).write_text(json.dumps(value))
    return analyze_saved_fight(tmp_path, Path("data/jobs/pld/7.4/actions.json"), use_cache=False)


def cast(time, ability, packet):
    return {"timestamp": time, "type": "cast", "sourceID": 1, "targetID": 2,
            "abilityGameID": ability, "packetID": packet}


def hit(cast, delay=1000, **fields):
    return {**cast, "type": "damage", "timestamp": cast["timestamp"] + delay,
            "amount": 1000, "hitType": 1, **fields}


@pytest.mark.parametrize("bonus,buff_time,expected", [
    (True, 1000, 275), (False, 1000, 220), (True, 1001, 220),
])
def test_fight_or_flight_requires_snapshot_and_recorded_packet_evidence(tmp_path, bonus, buff_time, expected):
    c = cast(1000, 10, 1)
    r = saved_pld(tmp_path, [c], [hit(c, buffs="1000076." if bonus else "")],
                  [buff(buff_time, 1000076)])
    assert r.potency_min == expected


def test_same_millisecond_fight_or_flight_removal_has_no_broad_grace(tmp_path):
    cs = [cast(t, 10, i) for i, t in enumerate([1000, 1001, 1002], 1)]
    r = saved_pld(tmp_path, cs, [hit(c, buffs="1000076.") for c in cs],
                  [buff(0, 1000076), buff(1000, 1000076, "removebuff")])
    assert r.potency_min == 275 + 220 + 220


def test_spell_priority_falloff_overkill_and_expiry_change_potency(tmp_path):
    cs = [cast(1000, 1, 1), cast(2000, 2, 2), cast(4000, 3, 3),
          cast(6000, 4, 4), cast(34000, 5, 5)]
    damage = [hit(c) for c in cs]
    damage.append(hit(cs[1], targetID=3))
    damage[-1]["amount"] = 400
    damage[-2]["overkill"] = 1000
    r = saved_pld(tmp_path, cs, damage, [buff(0, 1002673), buff(0, 1001368)])
    actions = {a.name: a for a in r.actions}
    assert actions["Holy Spirit"].potency_min == 500
    assert actions["Confiteor"].potency_min == 1400
    assert actions["Blade of Faith"].potency_min == 760
    assert actions["Blade of Truth"].potency_min == 880
    assert actions["Blade of Valor"].potency_min == 250


def test_circle_ticks_keep_application_buff_potion_and_penalty_snapshot(tmp_path):
    c = cast(1000, 9, 1)
    direct = hit(c, buffs="1000076.1000049.1002911.")
    tick = hit(c, delay=10000, abilityGameID=1000248, tick=True, buffs="")
    r = saved_pld(tmp_path, [c], [direct, tick],
                  [buff(0, 1000076), buff(2500, 1000076, "removebuff")])
    strength = 6450 * 101 // 100
    main = lambda s: 100 + 190 * (s - 440) // 440
    potion = main(strength + 541) / main(strength)
    assert r.pld is not None
    assert r.pld.circle.application_potency == pytest.approx(140 * 1.25 * 0.75 * potion)
    assert r.pld.circle.tick_potency == pytest.approx(30 * 1.25 * 0.75 * potion)
    assert r.potency_min == pytest.approx(170 * 1.25 * 0.75 * potion)
    assert r.pld.alignment is not None
    assert r.pld.alignment.inside_potency == pytest.approx(170 * 0.75 * potion)
    assert r.pld.alignment.outside_potency == 0


def test_alignment_uses_snapshot_packet_evidence_and_landed_fraction(tmp_path):
    cs = [cast(1000, 2, 1), cast(21000, 5, 2), cast(5000, 6, 3), cast(6000, 2, 4)]
    damage = [hit(cs[0], delay=22000, buffs="1000076."),
              hit(cs[1], buffs="", overkill=1000), hit(cs[2], buffs="")]
    damage.append(hit(cs[0], delay=22000, buffs="1000076.", targetID=3))
    r = saved_pld(tmp_path, cs, damage,
                  [buff(0, 1000076), buff(20000, 1000076, "removebuff")])
    assert r.pld is not None and r.pld.alignment is not None
    a = r.pld.alignment
    # Confiteor's delayed hits retain the cast snapshot and 40% AoE falloff.
    assert a.inside_potency == 700
    assert a.outside_potency == 250 + 580
    assert {f.action: f.potential_gain for f in a.outside} == {
        "Blade of Valor": 62.5, "Imperator": 145,
    }
    assert next(f for f in a.outside if f.action == "Imperator").seconds == 5
    # A completed Confiteor without any landed hit contributes no alignment potency.
    assert len(a.outside) == 2


def test_completed_casts_fake_records_and_hits_are_distinct(tmp_path):
    c = cast(1000, 1, 1)
    casts = [{**c, "type": "begincast", "timestamp": 0}, c,
             {**c, "timestamp": 2000, "packetID": 2, "fake": True}, cast(3000, 1, 3)]
    r = saved_pld(tmp_path, casts, [hit(c)])
    assert r.execution is not None
    assert dict(r.execution.cast_counts)["Holy Spirit"] == 2
    assert r.actions[0].hits == 1 and r.actions[0].uses == 1
    assert dict(r.ghosted) == {"Holy Spirit": 1}
