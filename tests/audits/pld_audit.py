"""Independent PLD arithmetic from recorded status intervals and damage packets.

The oracle reads status events directly, without calling spell replay, buff,
DoT, potency, potion, or auto-attack calculation helpers from the analyzer.
"""

import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from zipfile import ZipFile

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.targetability import targetable_intervals

BASE = {"Fast Blade": 220, "Riot Blade": 170, "Royal Authority": 200,
        "Total Eclipse": 120, "Prominence": 100, "Shield Lob": 100,
        "Shield Bash": 100, "Goring Blade": 700, "Expiacion": 450,
        "Circle of Scorn": 140, "Intervene": 150, "Imperator": 580,
        "Requiescat": 320, "Holy Spirit": 400, "Holy Circle": 100,
        "Atonement": 460, "Supplication": 500, "Sepulchre": 540,
        "Confiteor": 500, "Blade of Faith": 260, "Blade of Truth": 380,
        "Blade of Valor": 500, "Blade of Honor": 1000}
COMBO = {"Riot Blade": 330, "Royal Authority": 460, "Prominence": 220}
ENHANCED = {"Holy Spirit": 700, "Holy Circle": 350, "Confiteor": 1000,
            "Blade of Faith": 760, "Blade of Truth": 880, "Blade of Valor": 1000}
DIVINE = {"Holy Spirit": 500, "Holy Circle": 250}
FALLOFF = {"Expiacion", "Imperator", "Confiteor", "Blade of Faith",
           "Blade of Truth", "Blade of Valor", "Blade of Honor"}
PENALTIES = {101: 0.75, 102: 0.70, 103: 0.65, 104: 0.50, 105: 0.50,
             1085: 0.10, 4550: 0.85}


def audit_pld(tmp_path, archive, prefix):
    with ZipFile(Path("tests/fixtures/logs") / archive) as logs:
        for member in logs.namelist():
            if member.startswith(prefix + "/") and member.endswith(".json"):
                (tmp_path / Path(member).name).write_bytes(logs.read(member))

    def read(name):
        path = tmp_path / (name + ".json")
        return json.loads(path.read_text()) if path.exists() else []

    source = int(prefix.rsplit("source-", 1)[1])
    fight, master = read("fight"), read("master-data")
    assert isinstance(fight, dict)
    assert isinstance(master, dict)
    names = {a["gameID"]: a["name"] for a in master["abilities"]}
    damage, buffs, life = read("damage-events"), read("buff-events"), read("life-events")
    casts = [e for e in read("cast-events") if e.get("type") == "cast" and not e.get("fake")]
    own_buffs = [e for e in buffs if e.get("targetID") == source and e.get("sourceID") == source]
    initial = {a["ability"]: a for c in read("combatant-info-events") if c["sourceID"] == source
               for a in c.get("auras", ())}
    start, end = fight["startTime"], fight["endTime"]
    result = analyze_saved_fight(tmp_path, Path("data/jobs/pld/7.4/actions.json"), use_cache=False)
    assert result.unmatched == ()
    assert result.pld is not None
    assert result.potency_min == result.potency_max
    assert result.actions_since == "7.4"
    assert result.auto_attacks[0].potency_per_hit == pytest.approx(90 * 150 / 202)
    assert result.auto_attacks[0].weapon_delay_seconds == 2.24
    assert "Guardian" not in dict(result.ghosted)

    # Independent fixed-recast wait arithmetic on the established encounter
    # windows. Neither the cooldown replay nor living-window helper is used.
    actors = {a["id"]: a for a in master["actors"]}
    encounter_damage_path = tmp_path / "encounter-damage-events.json"
    windows = targetable_intervals(
        read("targetability-events"),
        read("encounter-damage-events") if encounter_damage_path.exists() else damage,
        read("encounter-overkill-events"), actors, start, end,
    )
    dead = []
    died = None
    for event in sorted(life, key=lambda e: e["timestamp"]):
        if event.get("targetID") != source:
            continue
        if event.get("type") == "death" and died is None:
            died = event["timestamp"]
        elif event.get("type") == "resurrect" and died is not None:
            dead.append((died, event["timestamp"]))
            died = None
    if died is not None:
        dead.append((died, end))
    for timing in result.pld.cooldown_timing:
        if timing.name == "Intervene":
            assert timing.minimum
            continue
        recast = 60000 if timing.name in {"Fight or Flight", "Imperator"} else 30000
        times_for_action = sorted(e["timestamp"] for e in casts
                                  if e.get("sourceID") == source
                                  and names[e["abilityGameID"]] == timing.name)
        if not times_for_action:
            assert timing.ready_seconds is None
            continue
        waits = []
        for prior, following in zip(times_for_action, [*times_for_action[1:], end]):
            wait = 0.0
            for a, b in windows:
                a, b = max(a, start, prior + recast), min(b, end, following)
                if b <= a:
                    continue
                wait += b - a
                wait -= sum(max(0, min(b, r) - max(a, d)) for d, r in dead)
            waits.append(wait / 1000)
        assert timing.ready_seconds == pytest.approx(sum(waits)), timing.name
        assert timing.longest_delay_seconds == pytest.approx(max(waits)), timing.name

    def status_active(status, time):
        # Consumption/removal is recorded at the cast's snapshot millisecond.
        # Inspect its preceding state, including grants at that millisecond.
        prior = [e for e in own_buffs if e["abilityGameID"] == status
                 and (e["timestamp"] < time or e["timestamp"] == time
                      and e["type"] in {"applybuff", "refreshbuff", "applybuffstack"})]
        grants = [e for e in prior if e["type"] in {"applybuff", "refreshbuff"}]
        grant = max(grants, key=lambda e: e["timestamp"], default=None)
        if grant is None:
            if status not in initial:
                return False
            began, expiry = start, end
        else:
            began = grant["timestamp"]
            expiry = began + grant["duration"]
        return (time <= expiry
                and not any(e["type"] == "removebuff" and e["timestamp"] >= began for e in prior)
                and not any(e["type"] == "death" and e.get("targetID") == source
                            and began <= e["timestamp"] < time for e in life))

    packet_casts = {(c["packetID"], c["abilityGameID"]): c for c in casts if c.get("packetID") is not None}
    times = {(e["packetID"], e["abilityGameID"]): e["timestamp"] for e in damage
             if e["type"] == "calculateddamage"}
    times.update({key: c["timestamp"] for key, c in packet_casts.items()})
    landed = [e for e in damage if e["type"] == "damage" and e.get("amount", 0) > 0 and e.get("hitType") != 10]
    applications = {(e["packetID"], e["targetID"], e.get("targetInstance", 0)): e
                    for e in landed if names[e["abilityGameID"]] == "Circle of Scorn" and not e.get("tick")}
    grouped = defaultdict(list)
    for hit in landed:
        grouped[hit["packetID"], hit["abilityGameID"]].append(hit)
    party = result.party_bonus_percent
    assert party is not None
    strength = 6450 * (100 + party) // 100
    main_factor = lambda stat: 100 + 190 * (stat - 440) // 440
    potion = main_factor(strength + 541) / main_factor(strength)
    totals = defaultdict(float)
    auto = potted = gain = hb_total = hb_weight = luck = maximum = 0.0
    normalized = defaultdict(list)
    spell_evidence = {}
    circle_direct = circle_ticks = 0.0
    alignment_inside = alignment_outside = 0.0
    alignment_scope = {"Goring Blade", "Imperator", "Confiteor", "Blade of Faith",
                       "Blade of Truth", "Blade of Valor", "Blade of Honor",
                       "Circle of Scorn", "Expiacion"}
    for hits in grouped.values():
        def full_damage(hit):
            return (hit["amount"] + max(0, hit.get("overkill", 0))) / (
                (1.628 if hit.get("hitType") == 2 else 1)
                * (1.25 if hit.get("directHit") else 1) * hit.get("multiplier", 1))

        primary = max(hits, key=full_damage)
        for hit in hits:
            key = hit["packetID"], hit["abilityGameID"]
            name = names[hit["abilityGameID"]]
            evidence = hit
            time = times.get(key, hit["timestamp"])
            if hit.get("tick"):
                assert name == "Circle of Scorn"
                evidence = applications[hit["packetID"], hit["targetID"], hit.get("targetInstance", 0)]
                time = times[evidence["packetID"], evidence["abilityGameID"]]
            statuses = {int(s) for s in str(evidence.get("buffs", "")).split(".") if s.isdigit()}
            base = 90 * 150 / 202 if name == "Attack" else BASE[name]
            if hit.get("tick"):
                base = 30
            elif hit.get("bonusPercent", 0) > 0:
                base = COMBO.get(name, base)
            if name in ENHANCED:
                enhancement = "None"
                if name in DIVINE and status_active(1002673, time):
                    base, enhancement = DIVINE[name], "Divine Might"
                elif status_active(1001368, time):
                    base, enhancement = ENHANCED[name], "Requiescat"
                spell_evidence[key] = enhancement
            if name in FALLOFF and hit is not primary:
                base *= 0.4
            if not hit.get("tick") and not hit.get("overkill") and hit.get("hitType") != 10:
                normalized[name].append(full_damage(hit) / base / (potion / 1.05 if 1000049 in statuses else 1))
            value = base
            if 1000076 in statuses and status_active(1000076, time):
                value *= 1.25
            value *= hit["amount"] / (hit["amount"] + max(0, hit.get("overkill", 0)))
            if 1002911 in statuses:
                value *= PENALTIES[fight["encounterID"]]
            potted_hit = 1000049 in statuses
            reduction = 50 if 1000044 in statuses else 25 if 1000043 in statuses else 0
            unpotted_value = value * main_factor(strength * (100 - reduction) // 100) / main_factor(strength)
            stat = strength + 541 if potted_hit else strength
            value *= main_factor(stat * (100 - reduction) // 100) / main_factor(stat)
            if potted_hit:
                potted += unpotted_value
                gain += value * potion - unpotted_value
                value *= potion
            if name in alignment_scope:
                if 1000076 in statuses and status_active(1000076, time):
                    alignment_inside += value / 1.25
                else:
                    alignment_outside += value
            if name == "Attack":
                auto += value
            else:
                totals[name] += value
            if name == "Circle of Scorn":
                if hit.get("tick"):
                    circle_ticks += value
                else:
                    circle_direct += value
            if not hit.get("tick"):
                # Food timing controls the expected Crit strength, not potency.
                fed = 1000048 in initial
                for e in sorted(buffs, key=lambda e: e["timestamp"]):
                    if e.get("targetID") == source and e["abilityGameID"] == 1000048 and e["timestamp"] <= hit["timestamp"]:
                        if e["type"] == "removebuff":
                            fed = False
                        elif e["type"] in {"applybuff", "refreshbuff"}:
                            fed = True
                crit = (1400 + 200 * ((3595 if fed else 3504) - 420) // 2780) / 1000
                bonus = (crit if hit.get("hitType") == 2 else 1) * (1.25 if hit.get("directHit") else 1) - 1
                hb_total += value * bonus
                hb_weight += value
                luck += value * bonus
                maximum += value * (1.25 * crit - 1)

    for action in result.actions:
        assert action.potency_min == pytest.approx(totals[action.name]), action.name
    assert result.auto_attacks[0].total_potency == pytest.approx(auto)
    assert result.potency_min == pytest.approx(sum(totals.values()) + auto)
    assert result.targetable_seconds is not None
    assert result.targetable_seconds > 0
    assert result.pps_min == pytest.approx((sum(totals.values()) + auto) / result.targetable_seconds)
    assert result.potion.potted_potency_min == pytest.approx(potted)
    assert result.potion.gained_potency_min == pytest.approx(gain)
    assert result.hit_bonus == pytest.approx(hb_total / hb_weight)
    assert result.luck_score == pytest.approx(luck / maximum)
    assert result.pld.circle.application_potency == pytest.approx(circle_direct)
    assert result.pld.circle.tick_potency == pytest.approx(circle_ticks)
    assert result.pld.alignment is not None
    assert result.pld.alignment.inside_potency == pytest.approx(alignment_inside)
    assert result.pld.alignment.outside_potency == pytest.approx(alignment_outside)
    assert sum(f.potential_gain for f in result.pld.alignment.outside) == pytest.approx(
        alignment_outside * .25,
    )
    for spell in result.pld.spell_counts:
        assert spell[3] > 0
    # Compare every landed spell against an independently recovered status.
    from ffxiv_potency.analysis.pld.state import replay_spells
    state = replay_spells(read("cast-events"), buffs, life, read("combatant-info-events"), names, source, start, end)
    for spell in state.spells:
        key = spell.packet, spell.ability_id
        if key in spell_evidence:
            assert spell.enhancement == spell_evidence[key]

    # Raw damage confirms conditional potency independently of event replay.
    # Spell and weaponskill references share Strength and the tank coefficient.
    reference = median(normalized["Fast Blade"] + normalized["Riot Blade"])
    for name in ENHANCED:
        if len(normalized[name]) >= 3:
            # Independent 95%-105% damage rolls on both samples permit a
            # relative ratio from 0.95/1.05 to 1.05/0.95. This is a damage
            # plausibility check, in addition to exact packet arithmetic above.
            ratio = median(normalized[name]) / reference
            assert 0.95 / 1.05 <= ratio <= 1.05 / 0.95, (name, ratio)
    # Auto-attacks use coefficient 195, while action damage uses 190.
    attack_factor = lambda stat: 100 + 195 * (stat - 440) // 440
    ratio = (median(normalized["Attack"]) / reference
             / (attack_factor(strength) / main_factor(strength)))
    assert 0.95 / 1.05 <= ratio <= 1.05 / 0.95
