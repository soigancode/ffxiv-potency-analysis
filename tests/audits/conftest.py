"""Independent Dancer log audits shared by fight-specific tests."""

import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from zipfile import ZipFile

import pytest

from ffxiv_potency.analysis import analyze_saved_fight

BASE = {
    "Standard Finish": 360,
    "Single Standard Finish": 540,
    "Technical Finish": 350,
    "Single Technical Finish": 540,
    "Double Technical Finish": 720,
    "Triple Technical Finish": 900,
    "Cascade": 220,
    "Fountain": 120,
    "Windmill": 120,
    "Bladeshower": 100,
    "Reverse Cascade": 280,
    "Fountainfall": 340,
    "Rising Windmill": 160,
    "Bloodshower": 200,
    "Fan Dance": 180,
    "Fan Dance II": 100,
    "Fan Dance III": 220,
    "Fan Dance IV": 460,
    "Saber Dance": 540,
    "Last Dance": 540,
    "Finishing Move": 850,
    "Double Standard Finish": 850,
    "Quadruple Technical Finish": 1300,
    "Tillana": 600,
    "Starfall Dance": 600,
    "Dance of the Dawn": 1000,
}
FALLOFF = {
    name: 0.4
    for name in [
        "Fan Dance III",
        "Fan Dance IV",
        "Saber Dance",
        "Last Dance",
        "Finishing Move",
        "Double Standard Finish",
        "Quadruple Technical Finish",
        "Tillana",
        "Dance of the Dawn",
    ]
} | {"Starfall Dance": 0.25}


@pytest.fixture
def audit_dnc():
    return _audit_dnc


def _audit_dnc(tmp_path, archive_name, prefix, expected, starting):
    with ZipFile(f"tests/fixtures/logs/{archive_name}") as archive:
        for member in archive.namelist():
            if member.startswith(prefix + "/") and member.endswith(".json"):
                (tmp_path / Path(member).name).write_bytes(archive.read(member))
    result = analyze_saved_fight(tmp_path, Path("data/jobs/dnc/7.4/actions.json"), use_cache=False)
    proc = result.dnc_procs
    assert proc is not None
    assert result.unmatched == ()
    actual = (
        result.source_name,
        result.gear_id,
        result.matched_damage_events,
        result.auto_attacks[0].hits,
        result.potion.uses,
        len(result.dnc_finishes),
        proc.feather_trials,
        proc.feathers_used,
        proc.feather_successes_min,
        proc.random_threefold,
    )
    assert actual == expected
    assert proc.starting_feathers == starting
    assert proc.gcd_to_feather_chance == pytest.approx(0.25)
    assert proc.expected_feathers == proc.feather_trials / 2
    assert proc.expected_threefold == proc.fan_trials / 2
    assert proc.feather_successes_min is not None
    initial_trials = sum(c for stage in proc.ready_procs[:2] for _, c in stage.trials)
    initial_extra = 0.0
    for stage in proc.ready_procs[:2]:
        assert stage.random_grants is not None
        initial_extra += stage.random_grants - stage.expected
    z = (0.5 * initial_extra + proc.feather_successes_min - proc.expected_feathers) / math.sqrt(
        initial_trials / 16 + proc.feather_trials / 4
    )
    assert proc.feather_luck_min == pytest.approx(50 * (1 + math.erf(z / math.sqrt(2))))
    assert proc.random_threefold is not None
    initial_grants = sum(
        stage.random_grants for stage in proc.ready_procs[:2] if stage.random_grants is not None
    )
    assert proc.combined_feather_luck_min == pytest.approx(
        100
        * (
            initial_grants
            / initial_trials
            * proc.feather_successes_min
            / proc.feather_trials
            * proc.random_threefold
            / proc.fan_trials
        )
        ** (1 / 3)
    )
    for stage in proc.ready_procs:
        assert stage.random_grants is not None and stage.guaranteed_grants is not None
        assert stage.unknown_consumed == stage.unknown_removals == 0
        assert stage.random_grants + stage.guaranteed_grants == (
            stage.random_consumed
            + stage.guaranteed_consumed
            + stage.overlaps
            + stage.overwritten
            + stage.expired
            + stage.death_lost
            + stage.remaining
        )
    master = json.loads((tmp_path / "master-data.json").read_text())
    names = {a["gameID"]: a["name"] for a in master["abilities"]}
    damage = json.loads((tmp_path / "damage-events.json").read_text())
    landed = [e for e in damage if e.get("type") == "damage" and e.get("amount", 0) > 0]
    packets = defaultdict(list)
    for hit in landed:
        packets[hit.get("packetID"), hit["abilityGameID"]].append(hit)
    party_dex = 6841
    potion = (100 + 237 * (party_dex + 541 - 440) // 440) / (100 + 237 * (party_dex - 440) // 440)
    source_id = int(prefix.rsplit("source-", 1)[1])
    buff_events = json.loads((tmp_path / "buff-events.json").read_text())
    own_buffs = [
        e for e in buff_events if e.get("sourceID") == source_id and e.get("targetID") == source_id
    ]
    snapshots = {
        (e.get("packetID"), e.get("abilityGameID")): e["timestamp"]
        for e in damage
        if e.get("type") == "calculateddamage"
    }
    snapshots.update(
        {
            (e.get("packetID"), e.get("abilityGameID")): e["timestamp"]
            for e in json.loads((tmp_path / "cast-events.json").read_text())
        }
    )
    casts = json.loads((tmp_path / "cast-events.json").read_text())
    cast_by_packet = {e.get("packetID"): names.get(e.get("abilityGameID")) for e in casts}
    for stage, random_status, guaranteed_status, parents in [
        (proc.ready_procs[0], "Silken Symmetry", "Flourishing Symmetry", {"Cascade", "Windmill"}),
        (proc.ready_procs[1], "Silken Flow", "Flourishing Flow", {"Fountain", "Bladeshower"}),
        (
            proc.ready_procs[2],
            "Threefold Fan Dance",
            "Threefold Fan Dance",
            {"Fan Dance", "Fan Dance II"},
        ),
    ]:
        grants = [e for e in own_buffs if e["type"] in {"applybuff", "refreshbuff"}]
        random_packets = {
            e["packetID"]
            for e in grants
            if names[e["abilityGameID"]] == random_status
            and (names.get(e.get("extraAbilityGameID")) or cast_by_packet.get(e.get("packetID")))
            in parents
        }
        guaranteed_packets = {
            e["packetID"]
            for e in grants
            if names[e["abilityGameID"]] == guaranteed_status
            and (names.get(e.get("extraAbilityGameID")) or cast_by_packet.get(e.get("packetID")))
            == "Flourish"
        }
        assert stage.random_grants == len(random_packets)
        assert stage.guaranteed_grants == len(guaranteed_packets)
    # Enumerate feasible histories independently, rather than aggregating extrema.
    generating = {"Reverse Cascade", "Fountainfall", "Rising Windmill", "Bloodshower"}
    draws = {}
    for hit in damage:
        if (
            names.get(hit.get("abilityGameID")) in generating
            and hit.get("amount", 0) > 0
            and hit.get("hitType") != 10
        ):
            packet = hit["packetID"]
            draws[packet] = min(draws.get(packet, hit["timestamp"]), hit["timestamp"])
    assert len(draws) == proc.feather_trials
    timeline = [(time, 0) for time in draws.values()]
    timeline.extend(
        (e["timestamp"], 1)
        for e in casts
        if names.get(e.get("abilityGameID")) in {"Fan Dance", "Fan Dance II"} and not e.get("fake")
    )
    timeline.extend(
        (e["timestamp"], 2)
        for e in json.loads((tmp_path / "life-events.json").read_text())
        if e["type"] == "death" and e.get("targetID") == source_id
    )
    possibilities = {(gauge, 0) for gauge in starting}
    for _, kind in sorted(timeline):
        if kind == 0:
            possibilities |= {(min(4, gauge + 1), count + 1) for gauge, count in possibilities}
        elif kind == 1:
            possibilities = {(gauge - 1, count) for gauge, count in possibilities if gauge > 0}
        else:
            possibilities = {(0, count) for _, count in possibilities}
    assert proc.feather_successes_min == min(count for _, count in possibilities)
    critical_stat, direct_stat = (3585, 1877) if result.gear_id == "relic_7_55" else (3549, 2035)
    critical_chance = (50 + 200 * (critical_stat - 420) // 2780) / 1000
    critical_bonus = (400 + 200 * (critical_stat - 420) // 2780) / 1000
    critical_multiplier = 1 + critical_bonus
    direct_chance = (550 * (direct_stat - 420) // 2780) / 1000
    totals = defaultdict(float)
    auto = potted = gain = luck = maximum = adjustment = 0.0
    for hits in packets.values():
        # At 40%/25% falloff, normalizing Crit/DH reveals the primary hit
        # despite different random rolls and event ordering.
        primary = max(
            hits,
            key=lambda h: (
                (h["amount"] + max(0, h.get("overkill", 0)))
                / (critical_multiplier if h.get("hitType") == 2 else 1)
                / (1.25 if h.get("directHit") else 1)
                / h.get("multiplier", 1)
            ),
        )
        for hit in hits:
            name = names[hit["abilityGameID"]]
            statuses = set(str(hit.get("buffs", "")).split("."))
            buffs = 1.05 ** len(statuses & {"1001821", "1001822"})
            # The landed row can retain a buff that expired after snapshotting.
            # Use the calculated event's time and the documented buff duration.
            time = snapshots.get((hit.get("packetID"), hit.get("abilityGameID")), hit["timestamp"])
            if name in {
                "Standard Finish",
                "Single Standard Finish",
                "Double Standard Finish",
                "Technical Finish",
                "Single Technical Finish",
                "Double Technical Finish",
                "Triple Technical Finish",
                "Quadruple Technical Finish",
                "Finishing Move",
            }:
                time -= 0.001
            buffs = 1.0
            for status, duration in [(1001821, 60000), (1001822, 20000)]:
                if str(status) not in statuses:
                    continue
                previous = [
                    e
                    for e in own_buffs
                    if e.get("abilityGameID") == status and e["timestamp"] <= time
                ]
                last = max(previous, key=lambda e: e["timestamp"], default=None)
                if last is None or (
                    last["type"] in {"applybuff", "refreshbuff"}
                    and time < last["timestamp"] + duration
                ):
                    buffs *= 1.05
            value = 90 * 216 / 208 / 1.2 if name == "Attack" else BASE[name]
            if hit.get("bonusPercent", 0) > 0 and name in {"Fountain", "Bladeshower"}:
                value = 280 if name == "Fountain" else 160
            if hit is not primary:
                value *= FALLOFF.get(name, 1)
            value *= buffs * hit["amount"] / (hit["amount"] + max(0, hit.get("overkill", 0)))
            if "1000049" in statuses:
                potted += value
                gain += value * (potion - 1)
                value *= potion
            if name == "Attack":
                auto += value
            else:
                totals[name] += value
            if name == "Starfall Dance":
                assert hit["hitType"] == 2 and hit["directHit"]
                continue
            outcome = (critical_multiplier if hit["hitType"] == 2 else 1) * (
                1.25 if hit.get("directHit") else 1
            )
            luck += value * (outcome - 1)
            maximum += value * (critical_multiplier * 1.25 - 1)
            active = {names[int(s)] for s in statuses if s.isdigit() and int(s) in names}
            crit = (0.10 if "Chain Stratagem" in active else 0) + (
                0.10 if "Battle Litany" in active else 0
            )
            crit += 0.02 if active & {"The Wanderer's Minuet", "Wanderer's Minuet"} else 0
            direct = (0.20 if "Battle Voice" in active else 0) + (
                0.03 if "Army's Paeon" in active else 0
            )
            if "Devilment" in active:
                crit += 0.20
                direct += 0.20
            adjustment += value * (
                (1 + min(1, critical_chance + crit) * critical_bonus)
                * (1 + min(1, direct_chance + direct) * 0.25)
                - (1 + critical_chance * critical_bonus) * (1 + direct_chance * 0.25)
            )
    assert {a.name: a.potency_min for a in result.actions} == pytest.approx(dict(totals))
    assert result.auto_attacks[0].total_potency == pytest.approx(auto)
    assert result.potency_min == result.potency_max == pytest.approx(sum(totals.values()) + auto)
    assert result.potion.potted_potency_min == pytest.approx(potted)
    assert result.potion.gained_potency_min == pytest.approx(gain)
    assert result.luck_score == pytest.approx(luck / maximum)
    assert result.adjusted_luck_score == pytest.approx(
        max(0, min(1, (luck - adjustment) / maximum))
    )
    assert sum(f.potency for f in result.dnc_finishes) == pytest.approx(
        sum(
            totals.get(n, 0)
            for n in (
                "Standard Finish",
                "Single Standard Finish",
                "Double Standard Finish",
                "Technical Finish",
                "Single Technical Finish",
                "Double Technical Finish",
                "Triple Technical Finish",
                "Quadruple Technical Finish",
                "Finishing Move",
            )
        )
    )
    # Estimate base auto potency directly from damage, independently of the profile.
    normal = defaultdict(list)
    for hit in landed:
        name = names[hit["abilityGameID"]]
        if (
            name in {"Attack", "Cascade"}
            and hit["hitType"] == 1
            and not hit.get("directHit")
            and "1000049" not in str(hit.get("buffs", ""))
        ):
            normal[name].append(
                (hit["amount"] + max(0, hit.get("overkill", 0))) / hit.get("multiplier", 1)
            )
    observed = mean(normal["Attack"]) / mean(normal["Cascade"]) * 220 * 1.2 * 208 / 216
    assert observed == pytest.approx(90, abs=2)
    return result
