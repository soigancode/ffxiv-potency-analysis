"""Barrage changes Shadowbite potency when the buff is consumed."""

from ffxiv_potency.analysis.bard.barrage import _barrage_shadowbite_packets
from ffxiv_potency.analysis.potency import _direct_potency


def test_barrage_shadowbite_uses_buff_window_including_removal_at_cast() -> None:
    names = {1: "Barrage", 2: "Shadowbite"}
    casts = [
        {"abilityGameID": 2, "sourceID": 4, "timestamp": 1000, "packetID": 10},
        {"abilityGameID": 2, "sourceID": 4, "timestamp": 2000, "packetID": 11},
        {"abilityGameID": 2, "sourceID": 4, "timestamp": 3000, "packetID": 12},
    ]
    buffs = [
        {"abilityGameID": 1, "sourceID": 4, "targetID": 4,
         "timestamp": 1500, "type": "applybuff", "duration": 10000},
        {"abilityGameID": 1, "sourceID": 4, "targetID": 4,
         "timestamp": 2000, "type": "removebuff"},
    ]

    packets = _barrage_shadowbite_packets(casts, buffs, names, 4)
    assert packets == {(11, 2)}
    action = {"name": "Shadowbite", "potency": {"base": 200, "barrage_potency": 300}}
    event = {"packetID": 11, "abilityGameID": 2}
    assert _direct_potency(action, event, is_primary_target=True, barrage=True) == (300, 300)
    assert _direct_potency(action, event, is_primary_target=True) == (200, 200)
