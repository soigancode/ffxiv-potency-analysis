"""Variable Bard actions must use landed damage and acknowledge uncertain rolls."""

import pytest

from ffxiv_potency.analysis.bard.variable_potency import _bard_damage_estimates


def test_pitch_perfect_immune_target_can_consume_full_hit() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "buffs": "base", "hitType": 1}
        for index in range(6)
    ]
    hit = {"type": "damage", "abilityGameID": 2, "amount": 18000,
           "timestamp": 800, "packetID": 10, "buffs": "base", "hitType": 1}
    cast = {"type": "cast", "abilityGameID": 2, "packetID": 10, "timestamp": 0}
    immune = {"type": "damage", "abilityGameID": 2, "amount": 0,
              "timestamp": 0, "hitType": 10}

    inferred, summaries = _bard_damage_estimates(
        references + [hit], [cast], [immune], names, 1.627
    )

    assert inferred[id(hit)][0] == 180  # Three stacks, 50% falloff.
    assert summaries[0].estimated_hits == 1


def test_pitch_perfect_reports_stack_and_falloff_for_ambiguous_hit() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": 10, "hitType": 1}
        for index in range(4)
    ]
    hit = {"type": "damage", "abilityGameID": 2, "amount": 10500,
           "timestamp": 800, "targetID": 10, "packetID": 10, "hitType": 1}
    cast = {"type": "cast", "abilityGameID": 2, "packetID": 10, "timestamp": 0}
    immune = {"type": "damage", "abilityGameID": 2, "amount": 0,
              "timestamp": 0, "hitType": 10}

    _, summaries = _bard_damage_estimates(references + [hit], [cast], [immune], names, 1.625)

    uncertain = summaries[0].pitch_uncertain_hits[0]
    assert uncertain.plausible_fits == ("1-stack full hit", "2-stack falloff hit")
    assert not uncertain.outside_expected
    assert uncertain.distance_from_bound_percent == pytest.approx(100 * (105 - 102.85) / 102.85)


def test_reference_damage_ignores_other_targets_and_clipped_overkill() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": 10, "buffs": "base", "hitType": 1}
        for index in range(4)
    ]
    references.extend(
        {"type": "damage", "abilityGameID": 1, "amount": 26400,
         "timestamp": index + 10, "targetID": 11, "buffs": "base", "hitType": 1}
        for index in range(6)
    )
    references.append(
        {"type": "damage", "abilityGameID": 1, "amount": 3000,
         "unmitigatedAmount": 22000, "overkill": 19000,
         "timestamp": 799, "targetID": 10, "buffs": "base", "hitType": 1}
    )
    hit = {"type": "damage", "abilityGameID": 2, "amount": 18000,
           "timestamp": 800, "packetID": 10, "targetID": 10,
           "buffs": "base", "hitType": 1}
    cast = {"type": "cast", "abilityGameID": 2, "packetID": 10, "timestamp": 0}
    immune = {"type": "damage", "abilityGameID": 2, "amount": 0,
              "timestamp": 0, "hitType": 10}

    inferred, summaries = _bard_damage_estimates(
        references + [hit], [cast], [immune], names, 1.627
    )

    assert inferred[id(hit)] == (180, False, 0.0)
    assert summaries[0].uncertain_hits == 0


def test_raid_buffs_and_medicated_use_fflogs_multiplier_for_classification() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": 10, "buffs": "", "hitType": 1,
         "multiplier": 1.0}
        for index in range(4)
    ]
    hit = {"type": "damage", "abilityGameID": 2, "amount": 54000,
           "timestamp": 800, "targetID": 10, "packetID": 10,
           "buffs": "medicated.raid.", "hitType": 1, "multiplier": 1.5}

    inferred, summaries = _bard_damage_estimates(references + [hit], [], [], names, 1.627)

    assert inferred[id(hit)] == (360, False, 0.0)
    assert summaries[0].uncertain_hits == 0


def test_pitch_perfect_accepts_six_percent_roll_with_baseline_tolerance() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": 10, "hitType": 1}
        for index in range(4)
    ]
    hit = {"type": "damage", "abilityGameID": 2, "amount": 33840,
           "timestamp": 800, "targetID": 10, "packetID": 10, "hitType": 1}

    inferred, summaries = _bard_damage_estimates(references + [hit], [], [], names, 1.625)

    assert inferred[id(hit)] == (360, False, 0.0)
    assert summaries[0].uncertain_hits == 0


def test_single_target_pitch_perfect_is_full_potency() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": 10, "hitType": 1}
        for index in range(4)
    ]
    hit = {"type": "damage", "abilityGameID": 2, "amount": 10300,
           "timestamp": 800, "targetID": 10, "packetID": 10, "hitType": 1}

    inferred, summaries = _bard_damage_estimates(references + [hit], [], [], names, 1.625)

    assert inferred[id(hit)] == (100, False, 0.0)
    assert summaries[0].outside_expected_hits == 0


def test_pitch_perfect_outside_interval_uses_nearest_potency_and_reports_it() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": 10, "hitType": 1}
        for index in range(4)
    ]
    hit = {"type": "damage", "abilityGameID": 2, "amount": 32000,
           "timestamp": 800, "targetID": 10, "packetID": 10, "hitType": 1}

    inferred, summaries = _bard_damage_estimates(references + [hit], [], [], names, 1.625)

    assert inferred[id(hit)][0] == 360
    assert summaries[0].outside_expected_hits == 1
    outside = summaries[0].outside_expected_details[0]
    assert outside.normalized_damage == 32000
    assert outside.potency == 360
    assert (outside.lower_damage, outside.upper_damage) == (33660, 38340)
    assert summaries[0].pitch_uncertain_hits[0].distance_from_bound_percent == pytest.approx(
        100 * (336.6 - 320) / 336.6
    )


def test_potted_pitch_perfect_uses_dexterity_factor_for_classification() -> None:
    names = {1: "Burst Shot", 2: "Pitch Perfect"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": 10, "hitType": 1}
        for index in range(4)
    ]
    potion_multiplier = 3837 / 3546
    hit = {"type": "damage", "abilityGameID": 2,
           "amount": round(36000 * 1.06 * potion_multiplier * 1.2),
           "timestamp": 800, "targetID": 10, "packetID": 10,
           "hitType": 1, "buffs": "1000049.", "multiplier": 1.05 * 1.2}

    inferred, summaries = _bard_damage_estimates(
        references + [hit], [], [], names, 1.625,
        potion_multiplier=potion_multiplier,
    )

    assert inferred[id(hit)] == (360, False, 0.0)
    assert summaries[0].uncertain_hits == 0


def test_apex_followed_by_blast_has_at_least_eighty_gauge() -> None:
    names = {1: "Burst Shot", 3: "Apex Arrow", 4: "Blast Arrow"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "buffs": "base", "hitType": 1}
        for index in range(6)
    ]
    hit = {"type": "damage", "abilityGameID": 3, "amount": 56000,
           "timestamp": 800, "packetID": 11, "buffs": "base", "hitType": 1}
    casts = [{"type": "cast", "abilityGameID": 3, "packetID": 11,
              "timestamp": 0, "sourceID": 5},
             {"type": "cast", "abilityGameID": 4, "timestamp": 2000,
              "sourceID": 5}]

    inferred, summaries = _bard_damage_estimates(
        references + [hit], casts, [], names, 1.627
    )

    assert inferred[id(hit)][0] == 560  # 80 gauge.
    assert summaries[0].estimated_hits == 1
    assert summaries[0].apex_uses[0].gauge == 80
    assert summaries[0].apex_uses[0].plausible_gauges == (80, 85)


def test_apex_targets_share_one_gauge_estimate() -> None:
    names = {1: "Burst Shot", 3: "Apex Arrow", 4: "Blast Arrow"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "targetID": target, "buffs": "base", "hitType": 1}
        for target in (10, 11) for index in range(4)
    ]
    first = {"type": "damage", "abilityGameID": 3, "amount": 56000,
             "timestamp": 800, "targetID": 10, "packetID": 12,
             "buffs": "base", "hitType": 1}
    second = {"type": "damage", "abilityGameID": 3, "amount": 59500,
              "timestamp": 900, "targetID": 11, "packetID": 12,
              "buffs": "base", "hitType": 1}
    casts = [{"abilityGameID": 3, "packetID": 12, "timestamp": 0, "sourceID": 5},
             {"abilityGameID": 4, "timestamp": 2000, "sourceID": 5}]

    inferred, summaries = _bard_damage_estimates(references + [first, second], casts, [], names, 1.627)

    assert inferred[id(first)][0] == inferred[id(second)][0]
    assert len(summaries[0].apex_uses) == 1
    assert summaries[0].apex_uses[0].hits == 2
    assert summaries[0].apex_uses[0].gauge == 85


def test_radiant_encore_uses_distinct_songs_consumed_by_finale() -> None:
    names = {1: "Burst Shot", 5: "Mage's Ballad", 6: "Army's Paeon",
             7: "Radiant Finale", 8: "Radiant Encore"}
    references = [
        {"type": "damage", "abilityGameID": 1, "amount": 22000,
         "timestamp": index, "buffs": "base", "hitType": 1}
        for index in range(6)
    ]
    first = {"type": "damage", "abilityGameID": 8, "amount": 70000,
             "timestamp": 1000, "packetID": 20, "buffs": "base", "hitType": 1}
    second = {"type": "damage", "abilityGameID": 8, "amount": 80000,
              "timestamp": 4000, "packetID": 21, "buffs": "base", "hitType": 1}
    casts = [
        {"abilityGameID": 5, "timestamp": 0, "sourceID": 2},
        {"abilityGameID": 7, "timestamp": 100, "sourceID": 2},
        {"abilityGameID": 8, "timestamp": 200, "sourceID": 2, "packetID": 20},
        {"abilityGameID": 5, "timestamp": 2000, "sourceID": 2},
        {"abilityGameID": 5, "timestamp": 2100, "sourceID": 2},
        {"abilityGameID": 6, "timestamp": 2200, "sourceID": 2},
        {"abilityGameID": 7, "timestamp": 3000, "sourceID": 2},
        {"abilityGameID": 8, "timestamp": 3100, "sourceID": 2, "packetID": 21},
    ]

    inferred, summaries = _bard_damage_estimates(
        references + [first, second], casts, [], names, 1.627
    )

    assert inferred[id(first)] == (700, False, 0.0)
    assert inferred[id(second)] == (800, False, 0.0)
    assert summaries[0].uncertain_hits == 0
