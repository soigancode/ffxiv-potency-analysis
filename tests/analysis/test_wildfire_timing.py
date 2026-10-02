"""Wildfire timing follows contributing casts, not their delayed damage hits."""

import pytest

from ffxiv_potency.analysis.mch.wildfire import MchWildfireTracker
from ffxiv_potency.reporting import wildfire_note


def test_chain_uses_cast_times_deduplicates_aoe_and_excludes_missing_hits():
    names = {1: "Wildfire", 2: "Drill", 3: "Blazing Shot"}
    casts = [
        {"type": "cast", "sourceID": 7, "timestamp": time,
         "packetID": packet, "abilityGameID": ability}
        for time, packet, ability in [
            (900, 1, 1), (1400, 2, 2), (3000, 3, 3), (5500, 4, 3), (7000, 5, 3)
        ]
    ]
    tracker = MchWildfireTracker(
        casts=list(reversed(casts)),
        buffs=[{"type": "applybuff", "sourceID": 7, "targetID": 7,
                "timestamp": 1000, "packetID": 1, "abilityGameID": 1}],
        names=names, actions={"Drill": {"type": "Weaponskill"}, "Blazing Shot": {"type": "Weaponskill"}},
        landed_by_packet={
            (2, 2): [{"timestamp": 1600}, {"timestamp": 1700}],
            (3, 3): [{"timestamp": 3500}],
            (4, 3): [{"timestamp": 5800}],
        },
        potion_windows=(), source_id=7, fight_start=0, fight_end=12000,
        potion_buff_id=1000049, potion_multiplier=1.1,
    )
    tracker.record({"timestamp": 11000}, 6, 240)
    result = tracker.summaries()[0]
    assert result.landed_weaponskills == 3
    assert result.potency == 720
    assert result.contributing_actions == ("Drill", "Blazing Shot", "Blazing Shot")
    assert result.contributing_times == (1.4, 3, 5.5)
    assert result.cast_seconds == pytest.approx(0.9)
    assert wildfire_note(result) == (
        "WF -> 0.50s -> Drill -> 1.60s -> BS -> 2.50s -> BS -> 5.50s -> WF expires\n"
        "Time to last GCD: 4.60s"
    )
    tracker.records.clear()
    assert tracker.summaries()[0].contributing_times == result.contributing_times
    tracker.names[4] = "Detonator"
    tracker.casts.append({"type": "cast", "sourceID": 7, "timestamp": 7000,
                          "packetID": 6, "abilityGameID": 4})
    tracker.record({"timestamp": 7800}, 6, 240)
    early = tracker.summaries()[0]
    assert early.ended_seconds == 7
    assert early.detonated_seconds == 7.8
    assert early.potency == result.potency
    assert " -> 1.50s -> WF detonates\n" in wildfire_note(early)


def test_precursor_cast_is_identified_without_a_negative_gap():
    from ffxiv_potency.analysis.mch.wildfire import MchWildfireSummary

    result = MchWildfireSummary(
        1.0, 11.0, 2, 480,
        contributing_actions=("Drill", "Blazing Shot"),
        contributing_times=(0.7, 2.5), cast_seconds=0.9,
    )
    assert wildfire_note(result) == (
        "WF -> Drill (cast 0.20s before WF) -> 1.80s -> BS\n"
        "Time to last GCD: 1.60s"
    )
