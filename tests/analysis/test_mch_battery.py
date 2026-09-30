"""Resource resolution is distinct from damage landing and target count."""

import pytest

from ffxiv_potency.analysis.mch.battery import mch_battery_events
from ffxiv_potency.analysis.pets import _reconstruct_pet_deployments
from ffxiv_potency.analysis.profiles import _PetProfile


@pytest.mark.parametrize("events,combo,expected", [
    ([{"type": "calculateddamage", "unpaired": True}], False, 70),
    ([{"type": "calculateddamage"}, {"type": "damage"}], False, 70),
    ([{"type": "calculateddamage", "targetID": 3},
      {"type": "calculateddamage", "targetID": 4},
      {"type": "damage", "targetID": 4}], False, 70),
    ([{"type": "calculateddamage", "bonusPercent": 200, "unpaired": True}], True, 70),
    ([{"type": "calculateddamage", "unpaired": True}], True, 50),
    ([{"type": "calculateddamage", "hitType": 10}], False, 50),
    ([{"type": "calculateddamage", "amount": 0}], False, 50),
    ([{"type": "calculateddamage", "sourceID": 99}], False, 50),
])
def test_mch_battery_counts_resolved_cast_once_and_requires_combo(events, combo, expected):
    events = [{"sourceID": 2, "packetID": 1, "abilityGameID": 1,
               "amount": 100, **event} for event in events]
    casts = [{"timestamp": 1000, "sourceID": 2, "packetID": 1, "abilityGameID": 1},
             {"timestamp": 2000, "sourceID": 2, "packetID": 2, "abilityGameID": 2}]
    actions = {"Builder": {"gauge_gains": [
        {"gauge": "Battery Gauge", "amount": 20, "requires_combo": combo},
    ]}}
    profiles = {"Automaton Queen": _PetProfile(
        .89, "Battery Gauge", 50, 100, "Automaton Queen",
    )}
    deployments, _ = _reconstruct_pet_deployments(
        casts, actions, {1: "Builder", 2: "Automaton Queen"}, {}, profiles, 0,
        initial_gauges={"Battery Gauge": 50},
        gauge_events_by_packet={"Battery Gauge": mch_battery_events(events, 2)},
    )
    assert deployments[0].gauge_spent == expected
    assert not deployments[0].gauge_assumed
