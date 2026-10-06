"""Recorded Infuriate recharge, including caps, missing evidence and cleaves."""

from ffxiv_potency.analysis.war.infuriate import infuriate_timing

NAMES = {1: 'Infuriate', 2: 'Fell Cleave'}
ACTIONS = {'Infuriate': {'recast_seconds': 60, 'description': ['Maximum Charges: 2']}}


def cast(time):
    return {'timestamp': time, 'type': 'cast', 'sourceID': 1, 'abilityGameID': 1,
            'packetID': time}


def hit(time, packet=1, **extra):
    return {'timestamp': time, 'type': 'damage', 'sourceID': 1, 'abilityGameID': 2,
            'packetID': packet, 'amount': 100, **extra}


def timing(casts=(), damage=(), begin=130000, finish=160000, end=240000):
    return infuriate_timing(casts, damage, NAMES, ACTIONS, 1, begin, finish, end)


def test_cap_synchronizes_unknown_opening_and_pauses_recharge():
    result = timing((cast(0), cast(130000), cast(140000)))
    assert result.opening_charges == 2
    assert result.closing_charges == 0
    assert result.next_charge_after_end == 30


def test_spender_reduction_applies_once_for_multiple_targets_and_at_snapshot():
    damage = (hit(165000), hit(165100),
              hit(164000, type='calculateddamage'))
    result = timing((cast(0), cast(130000), cast(140000)), damage)
    assert result.next_charge_after_end == 25


def test_reduction_can_restore_charge_immediately():
    result = timing((cast(0), cast(130000), cast(140000)), (hit(187000),))
    assert result.next_charge_after_end == 27


def test_ticks_ghosts_and_other_players_do_not_reduce_recharge():
    result = timing((cast(0), cast(130000), cast(140000)),
                    (hit(150000, tick=True), hit(150100, packet=2, amount=0),
                     hit(150200, packet=3, sourceID=2)))
    assert result.next_charge_after_end == 30


def test_reduction_at_cap_does_not_precharge_next_recovery():
    result = timing((cast(0), cast(130000), cast(140000)), (hit(125000),))
    assert result.next_charge_after_end == 30


def test_missing_opening_evidence_is_unknown_until_charge_cap_is_proven():
    result = timing((cast(0), cast(10000)), begin=20000, finish=30000)
    assert result.opening_charges is None
    assert result.closing_charges is None
    assert timing().opening_charges is None


def test_window_boundaries_precede_casts_and_include_recovery():
    result = timing((cast(0), cast(130000), cast(160000)), finish=190000)
    assert result.opening_charges == 2
    assert result.closing_charges == 1
    assert result.next_charge_after_end == 0
