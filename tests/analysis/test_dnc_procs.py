"""Resource evidence, censored feather gains, and separately observed Fan procs."""

import json
from pathlib import Path

from ffxiv_potency.analysis.dnc.procs import summarize_dnc_procs

ACTIONS = {
    a["name"]: a for a in json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())["actions"]
}
ABILITIES = {
    1: "Reverse Cascade",
    2: "Bloodshower",
    3: "Fan Dance",
    4: "Fan Dance II",
    5: "Fan Dance III",
    6: "Flourish",
    1001820: "Threefold Fan Dance",
}


def event(time, packet, ability, **extra):
    return dict(
        timestamp=time,
        packetID=packet,
        abilityGameID=ability,
        sourceID=1,
        targetID=10,
        type="cast",
        **extra,
    )


def resolution(cast, **extra):
    return {**cast, "type": "calculateddamage", "amount": 100, "hitType": 1, **extra}


def proc(cast, kind="applybuff", **extra):
    return {
        **cast,
        "type": kind,
        "targetID": 1,
        "abilityGameID": 1001820,
        "extraAbilityGameID": cast["abilityGameID"],
        **extra,
    }


def analyze(casts, damage, buffs=None, life=()):
    return summarize_dnc_procs(casts, damage, buffs, list(life), ABILITIES, ACTIONS, 1)


def test_aoe_rolls_once_and_calculated_ghosts_still_offer_resources():
    casts = [event(100, 1, 2), event(200, 2, 1), event(300, 3, 1)]
    damage = [
        resolution(casts[0]),
        resolution(casts[0], targetID=11),
        resolution(casts[0], type="damage", timestamp=150),
        resolution(casts[1]),
        resolution(casts[2], amount=0, hitType=10),
    ]
    result = analyze(casts, damage)
    assert result.feather_trials == 2
    assert result.expected_feathers == 1
    assert (result.feathers_gained_min, result.feathers_gained_max) == (0, 2)
    assert result.random_threefold is None


def test_spending_requires_gains_after_initial_four_and_cap_losses_are_censored():
    casts = [event(i * 100, i, 3) for i in range(1, 5)]
    casts += [event(500, 5, 1), event(600, 6, 3), event(700, 7, 1)]
    result = analyze(casts, [resolution(c) for c in casts], [])
    assert result.feathers_used == 5
    assert result.expected_feathers == 1
    assert (result.feathers_gained_min, result.feathers_gained_max) == (1, 2)
    assert (result.feather_successes_min, result.feather_successes_max) == (1, 2)


def test_feathers_at_cap_can_roll_successfully_without_becoming_usable():
    casts = [event(i * 100, i, 1) for i in range(1, 7)]
    result = analyze(casts, [resolution(c) for c in casts], [])
    assert (result.feathers_gained_min, result.feathers_gained_max) == (0, 4)
    assert result.feather_successes_max == 6


def test_death_resets_inventory_but_other_players_deaths_do_not():
    casts = [event(100, 1, 1), event(300, 2, 1), event(400, 3, 3)]
    damage = [resolution(c) for c in casts]
    result = analyze(casts, damage, [], [{"timestamp": 200, "type": "death", "targetID": 1}])
    assert (result.feathers_gained_min, result.feathers_gained_max) == (1, 2)
    other = analyze(casts, damage, [], [{"timestamp": 200, "type": "death", "targetID": 2}])
    assert other.feathers_gained_min == 0


def test_unexplained_spenders_do_not_turn_missing_evidence_into_bad_luck():
    casts = [event(i * 100, i, 3) for i in range(1, 6)]
    result = analyze(casts, [], [])
    assert result.feathers_used == 5
    assert result.feathers_gained_min is None
    assert result.feather_successes_min is None


def test_random_refreshes_are_separate_from_flourish_and_foreign_procs():
    casts = [event(100, 1, 3), event(200, 2, 4), event(300, 3, 6), event(400, 4, 5)]
    buffs = [
        proc(casts[0]),
        proc(casts[0]),
        proc(casts[1], "refreshbuff"),
        proc(casts[2]),
        proc(casts[1], sourceID=2),
        proc(casts[1], targetID=2),
    ]
    result = analyze(casts, [resolution(c) for c in casts], buffs)
    assert result.fan_trials == 2
    assert result.expected_threefold == 1
    assert result.random_threefold == 2
    assert result.guaranteed_threefold == 1
    assert result.fan_three_uses == 1
    unknown = analyze(casts, [], [proc(casts[0], packetID=None)])
    assert unknown.random_threefold is None


def test_proc_application_proves_a_resolution_even_if_damage_is_missing():
    cast = event(100, 1, 3)
    result = analyze([cast], [], [proc(cast)])
    assert result.fan_trials == 1
    assert result.random_threefold == 1


CHAIN_ABILITIES = ABILITIES | {
    10: "Cascade",
    11: "Windmill",
    12: "Fountain",
    13: "Bladeshower",
    14: "Fountainfall",
    15: "Rising Windmill",
    20: "Silken Symmetry",
    21: "Flourishing Symmetry",
    22: "Silken Flow",
    23: "Flourishing Flow",
}


def ready_grant(cast, status, kind="applybuff"):
    return proc(cast, kind, abilityGameID=status, duration=30000)


def removal(time, status):
    return {
        "timestamp": time,
        "type": "removebuff",
        "abilityGameID": status,
        "sourceID": 1,
        "targetID": 1,
    }


def chain(casts, damage, buffs, life=()):
    return summarize_dnc_procs(casts, damage, buffs, list(life), CHAIN_ABILITIES, ACTIONS, 1)


def test_first_stage_counts_combo_bonuses_and_deduplicates_aoe_rolls():
    casts = [
        event(100, 1, 10),
        event(200, 2, 11),
        event(300, 3, 12),
        event(400, 4, 12),
        event(500, 5, 13),
    ]
    hits = [
        resolution(casts[0]),
        resolution(casts[1]),
        resolution(casts[1], targetID=11),
        resolution(casts[2], bonusPercent=0),
        resolution(casts[3], bonusPercent=57),
        resolution(casts[4], bonusPercent=37),
    ]
    buffs = [ready_grant(casts[0], 20), ready_grant(casts[0], 20), ready_grant(casts[4], 22)]
    symmetry, flow, _ = chain(casts, hits, buffs).ready_procs
    assert symmetry.trials == (("Cascade", 1), ("Windmill", 1))
    assert symmetry.expected == 1
    assert symmetry.random_grants == 1
    assert symmetry.overwritten == 0
    assert flow.trials == (("Bladeshower", 1), ("Fountain", 1))
    assert flow.expected == 1
    assert flow.random_grants == 1


def test_chain_separates_guaranteed_grants_and_conditional_from_full_use_expectations():
    casts = [
        event(100, 1, 10),
        event(200, 2, 12),
        event(300, 3, 6),
        event(400, 4, 1),
        event(500, 5, 14),
    ]
    buffs = [
        ready_grant(casts[0], 20),
        ready_grant(casts[2], 21),
        ready_grant(casts[2], 23),
        ready_grant(casts[2], 1001820),
    ]
    result = chain(
        casts,
        [resolution(c, bonusPercent=57) if c is casts[1] else resolution(c) for c in casts],
        buffs,
    )
    assert result.ready_procs[0].random_grants == 1
    assert result.ready_procs[0].guaranteed_grants == 1
    assert result.ready_procs[1].guaranteed_grants == 1
    # One expected random initial grant plus two guaranteed initial grants,
    # each rolling for a feather. Later Fan rolls add another factor of 0.5.
    assert result.full_use_expected_feathers == 1.5
    assert result.full_use_expected_random_threefold == 0.75
    assert result.expected_feathers == 1
    missing = chain(casts, [], None)
    assert missing.full_use_expected_feathers is None
    assert missing.ready_procs[0].random_grants is None


def test_ready_effect_lifecycle_tracks_overlap_overwrite_expiry_death_and_unknown_origin():
    casts = [
        event(100, 1, 10),
        event(200, 2, 6),
        event(300, 3, 1),
        event(400, 4, 10),
        event(500, 5, 10),
        event(40000, 6, 10),
    ]
    buffs = [
        ready_grant(casts[0], 20),
        ready_grant(casts[1], 21),
        removal(300, 20),
        removal(300, 21),
        ready_grant(casts[3], 20),
        ready_grant(casts[4], 20, "refreshbuff"),
        removal(30500, 20),
        ready_grant(casts[5], 20),
        removal(41000, 20),
        removal(42000, 21),
    ]
    life = [{"timestamp": 41000, "type": "death", "targetID": 1}]
    symmetry = chain(casts, [resolution(c) for c in casts], buffs, life).ready_procs[0]
    assert symmetry.uses == 1
    assert (symmetry.random_consumed, symmetry.guaranteed_consumed, symmetry.overlaps) == (1, 1, 1)
    assert (symmetry.overwritten, symmetry.expired, symmetry.death_lost) == (1, 1, 1)
    assert symmetry.unknown_removals == 1
    assert symmetry.remaining == 0
    initial = chain([event(100, 1, 1)], [], [removal(100, 20)]).ready_procs[0]
    assert initial.random_grants == 0
    assert initial.random_consumed == 0
    assert initial.unknown_consumed == 1


def test_threefold_tracks_random_and_flourish_origins_of_same_status():
    casts = [event(100, 1, 3), event(200, 2, 6), event(300, 3, 5)]
    buffs = [proc(casts[0]), proc(casts[1], "refreshbuff"), removal(300, 1001820)]
    threefold = chain(casts, [resolution(c) for c in casts], buffs).ready_procs[2]
    assert threefold.random_grants == threefold.guaranteed_grants == 1
    assert threefold.overwritten == 1
    assert threefold.random_consumed == 0
    assert threefold.guaranteed_consumed == 1
    assert threefold.overlaps == 0


def test_removal_matching_allows_timestamp_rounding_but_not_nearby_expiry():
    casts = [event(100, 1, 6), event(200, 2, 14), event(1000, 3, 6), event(31020, 4, 14)]
    buffs = [
        ready_grant(casts[0], 23),
        removal(201, 23),
        ready_grant(casts[2], 23),
        removal(31000, 23),
    ]
    flow = chain(casts, [], buffs).ready_procs[1]
    assert flow.guaranteed_consumed == 1
    assert flow.expired == 1
