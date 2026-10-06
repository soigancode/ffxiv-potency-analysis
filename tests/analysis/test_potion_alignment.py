"""Snapshot coverage is independent of cast/hit boundary timing."""

from ffxiv_potency.analysis.potion_alignment import PotionAlignment


def hit(packet, time, *, potted=True, tick=False):
    return {'type': 'damage', 'sourceID': 1, 'abilityGameID': 7, 'packetID': packet,
            'timestamp': time, 'amount': 100, 'tick': tick,
            'buffs': '1000049' if potted else ''}


def cast(packet, time):
    return {'type': 'cast', 'sourceID': 1, 'abilityGameID': 7,
            'packetID': packet, 'timestamp': time}


def test_late_potted_impact_is_covered_and_ticks_do_not_create_losses():
    evidence = PotionAlignment([hit(1, 31000), hit(1, 33000, potted=False, tick=True)],
                              1, 1000049, 1000, 30000)
    assert evidence.inside(cast(1, 29900))
    assert not evidence.outside(cast(1, 29900))


def test_cast_inside_boundary_does_not_override_unpotted_hit():
    evidence = PotionAlignment([hit(1, 30100, potted=False)], 1, 1000049, 1000, 30000)
    assert not evidence.inside(cast(1, 29900))
    assert evidence.outside(cast(1, 29900))


def test_only_unpotted_targets_contribute_to_estimated_gain():
    hits = [hit(1, 29900), hit(1, 30100, potted=False)]
    rows = [(hits[0], 29800, 'Action', 1080), (hits[1], 29800, 'Action', 400)]
    evidence = PotionAlignment(hits, 1, 1000049, 1000, 30000, rows, 1.08)
    assert evidence.outside(cast(1, 29800))
    assert evidence.gain_note((cast(1, 29800),)) == ' Estimated potion gain missed: 32.0 potency (direct hits).'


def test_ghosts_do_not_lose_potion_potency():
    evidence = PotionAlignment([hit(1, 20000)], 1, 1000049, 1000, 30000)
    assert not evidence.outside(cast(2, 31000))


def test_missing_damage_keeps_cast_timing_as_fallback():
    evidence = PotionAlignment([], 1, 1000049, 1000, 30000)
    assert evidence.outside(cast(1, 31000))
    assert not evidence.gain_note((cast(1, 31000),))
