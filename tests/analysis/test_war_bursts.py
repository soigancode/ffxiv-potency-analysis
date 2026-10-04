"""WAR sequence boundaries, potion snapshots and shared recasts."""

import pytest

from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.diagnostics import summarize_alignment, summarize_timing
from ffxiv_potency.analysis.models import PotionWindow
from ffxiv_potency.analysis.profiles import _load_combat_profile
from ffxiv_potency.analysis.targetability import TargetableTime
from ffxiv_potency.analysis.war.bursts import (
    WarBurst,
    WarPotionBurst,
    summarize_bursts,
    summarize_potion_bursts,
)

NAMES = {1: 'Inner Release', 2: 'Fell Cleave', 3: 'Decimate', 4: 'Primal Rend',
         5: 'Primal Ruination', 6: 'Primal Wrath', 7: 'Inner Chaos',
         8: 'Upheaval', 9: 'Orogeny', 10: 'Onslaught'}


def cast(time, ability, packet=None, source=1):
    return {'timestamp': time, 'type': 'cast', 'sourceID': source, 'abilityGameID': ability,
            'packetID': packet if packet is not None else time}


def test_ir_counts_casts_without_hits_and_followups_after_ir_expires():
    casts = [cast(0, 1), cast(2000, 2), cast(4000, 3), cast(6000, 2),
             cast(18000, 2), cast(25000, 4), cast(40000, 5), cast(20000, 6)]
    buffs = [{'timestamp': 6000, 'type': 'removebuff', 'targetID': 1,
              'abilityGameID': 1001177}]
    # Missing landed records must not turn a completed cast into a missing cast.
    rows = summarize_bursts(casts, [], buffs, [], NAMES, 1, 0, 60000)
    assert rows == (WarBurst(0, 3, 1, 1, 1),)
    assert _decode(_encode(rows[0]), WarBurst) == rows[0]


def test_next_ir_bounds_followups_and_duplicate_aoe_casts_count_once():
    casts = [cast(0, 1), cast(2000, 3), cast(2000, 3), cast(5000, 1), cast(6000, 4)]
    rows = summarize_bursts(casts, [], [], [], NAMES, 1, 0, 60000)
    assert rows[0] == WarBurst(0, 1, 0, 0, 0)
    assert rows[1] == WarBurst(5, 0, 1, 0, 0)


def test_pre_pull_ir_includes_opening_cast_before_report_start():
    casts = [cast(-312, 2), cast(2000, 2), cast(4000, 3)]
    combatants = [{'sourceID': 1, 'auras': [{'ability': 1001177}]}]
    result = summarize_bursts(casts, [], [], combatants, NAMES, 1, 0, 60000)
    assert result == (WarBurst(None, 3, 0, 0, 0),)


def test_pre_pull_ir_duration_is_not_fabricated_when_only_removal_is_recorded():
    casts = [cast(10649, 2), cast(13143, 2), cast(15639, 2)]
    combatants = [{'sourceID': 1, 'auras': [{'ability': 1001177}]}]
    buffs = [{'timestamp': 15639, 'type': 'removebuff', 'targetID': 1,
              'abilityGameID': 1001177}]
    result = summarize_bursts(casts, [], buffs, combatants, NAMES, 1, 0, 60000)
    assert result[0].spenders == 3


def test_potion_casts_and_damage_are_separate_with_aoe_autos_and_snapshot_tail():
    casts = [cast(0, 1), cast(1000, 3), cast(1000, 3), cast(25000, 7),
             cast(29000, 8), cast(10000, 10)]
    def hit(time, ability, potency, buffs='999.1002677.'):
        return ({**cast(time, ability), 'type': 'damage', 'buffs': buffs}, time,
                NAMES.get(ability, 'Attack'), potency)
    rows = [hit(1000, 3, 110, '999.1001177.1002677.'),
            hit(1000, 3, 110, '999.1001177.1002677.'),
            hit(25000, 7, 220), hit(29000, 8, 110), hit(30500, 99, 55, '999.')]
    windows = (PotionWindow(0, 30), PotionWindow(40, 70))
    result = summarize_potion_bursts(casts, rows, windows, NAMES, 1, 0, 999, 1.1)
    b = result[0]
    assert dict(b.casts) == {'IR spenders': 1, 'Infuriate': 0, 'Nascent Chaos': 1, 'Primal Rend': 0,
                            'Primal Ruination': 0, 'Primal Wrath': 0,
                            'Upheaval/Orogeny': 1, 'Onslaught': 1}
    assert b.base_potency == pytest.approx(550)
    assert b.gained_potency == pytest.approx(55)
    assert b.unbuffed_hits == 1
    assert result[1].base_potency == 0
    assert _decode(_encode(b), WarPotionBurst) == b


def test_unknown_potion_window_uses_recorded_buff_packets_only():
    casts = [cast(1000, 7), cast(2000, 10)]
    rows = [({**casts[0], 'buffs': '999.1002677.'}, 1000, 'Inner Chaos', 110)]
    result = summarize_potion_bursts(casts, rows,
        (PotionWindow(None, None, 1, 1, inferred=True),), NAMES, 1, 0, 999, 1.1)[0]
    assert dict(result.casts)['Nascent Chaos'] == 1
    assert dict(result.casts)['Onslaught'] == 0


def test_potion_totals_keep_revival_counterfactual_and_effective_tempest_state():
    e = {**cast(1000, 7), 'buffs': '999.1002677.',
         '_unpotted_potency': 75, '_tempest_factor': 1}
    row = summarize_potion_bursts([e], [(e, 1000, 'Inner Chaos', 85)],
        (PotionWindow(0, 30),), NAMES, 1, 0, 999, 1.1)[0]
    assert row.base_potency == 75
    assert row.gained_potency == 10
    assert row.unbuffed_hits == 1


def test_upheaval_and_orogeny_share_one_recharge_timeline():
    casts = [cast(0, 8), cast(30000, 9), cast(60000, 8)]
    rows = summarize_timing('warrior', casts, [], {'Upheaval': {'recast_seconds': 30}},
        NAMES, [], 1, 0, 90000, TargetableTime(90, 'events', ((0, 90000),)))
    assert len(rows) == 1
    assert rows[0].name == 'Upheaval/Orogeny'
    assert rows[0].ready_seconds == 0


def test_war_has_no_hypothetical_ir_alignment_gain():
    assert summarize_alignment('warrior', [], [], {}, 1, 0, 60000, {},
                               _load_combat_profile('warrior'), set()) == ()
