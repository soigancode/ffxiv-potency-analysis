"""Bard song durations use buff removals and truncated final windows."""

from ffxiv_potency.analysis.bard.songs import _bard_song_durations


def test_song_averages_use_removal_and_short_final_song() -> None:
    names = {1: "Mage's Ballad", 2: "Army's Paeon"}
    casts = [
        {"sourceID": 4, "timestamp": 0, "abilityGameID": 1},
        {"sourceID": 4, "timestamp": 41000, "abilityGameID": 2},
        {"sourceID": 4, "timestamp": 80000, "abilityGameID": 1},
    ]
    buffs = [
        {"type": "removebuff", "targetID": 4, "abilityGameID": 1, "timestamp": 40000},
        {"type": "removebuff", "targetID": 4, "abilityGameID": 2, "timestamp": 79500},
    ]
    assert _bard_song_durations(casts, buffs, names, 4, 90000) == (
        ("Army's Paeon", 38.5), ("Mage's Ballad", 25.0)
    )
