"""Potion placement diagnostics use recorded WAR sequences, not rotation templates."""

from ffxiv_potency.analysis.burst_opportunities import BurstAction, BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.war.potion_alignment import annotate_potion_alignment

NAMES = {1: 'Inner Release', 2: 'Fell Cleave', 3: 'Primal Rend',
         4: 'Primal Ruination', 5: 'Primal Wrath', 6: 'Inner Chaos'}
ACTIONS = {'Inner Release': {'description': ['Grants 3 stacks of Inner Release']},
           'Fell Cleave': {'recast_seconds': 2.5}}


def cast(time, ability):
    return {'timestamp': time, 'type': 'cast', 'sourceID': 1,
            'abilityGameID': ability, 'packetID': time}


def grant(time, status=1001177, duration=15000):
    return {'timestamp': time, 'type': 'applybuff', 'sourceID': 1, 'targetID': 1,
            'abilityGameID': status, 'duration': duration}


def annotate(casts, buffs=(), begin=10, finish=40, packets=(), life=(), actions=ACTIONS,
             damage=()):
    window = BurstWindow(begin, finish, tuple(BurstAction(name, 0, 0, 0) for name in
        ('IR spenders', 'Nascent Chaos', 'Primal Rend', 'Primal Ruination', 'Primal Wrath')),
        1000, 1000, 1000)
    return annotate_potion_alignment(window, casts, buffs, NAMES, actions, 1, 0,
                                    120000, packets, life, damage=damage)


def action(window, name):
    return next(a for a in window.actions if a.name == name)


def test_pre_potion_spenders_and_wrath_are_marked_even_with_zero_expected_casts():
    casts = (cast(0, 1), cast(1000, 2), cast(3500, 2), cast(6000, 2),
             cast(7000, 5), cast(11000, 3), cast(13500, 4))
    window = annotate(casts, (grant(0),))
    assert action(window, 'IR spenders').review
    assert '3 IR spenders' in action(window, 'IR spenders').notes[0]
    assert 'before this potion' in action(window, 'Primal Wrath').notes[0]
    assert not action(window, 'Primal Rend').review
    assert len(window.before_window_notes) == 2
    assert not window.after_window_notes
    assert window.actual_package_potency == window.best_package_potency == 1000
    assert _decode(_encode(window), BurstWindow) == window


def test_previous_held_ruination_does_not_make_current_complete_ir_look_incomplete():
    casts = (cast(0, 1), cast(1000, 2), cast(3500, 2), cast(6000, 2),
             cast(34000, 3), cast(54000, 4), cast(65000, 1),
             cast(67500, 2), cast(70000, 2), cast(72500, 2),
             cast(74000, 5), cast(76000, 3), cast(78500, 4))
    window = annotate(casts, (grant(0), grant(65000)), begin=53, finish=83)
    assert not window.alignment_notes
    assert not any(a.review for a in window.actions)


def test_potted_snapshot_overrides_cast_just_before_recorded_boundary():
    casts = (cast(8000, 1), cast(9900, 2), cast(12500, 2), cast(15000, 2))
    window = annotate(casts, (grant(8000),), packets=(('IR spenders', ((9900, 2),)),))
    assert not action(window, 'IR spenders').review


def test_late_ir_at_fight_end_marks_limited_remaining_time():
    casts = (cast(3000, 1), cast(4000, 2), cast(6500, 2))
    window = annotate(casts, (grant(3000),), begin=0, finish=8)
    assert action(window, 'IR spenders').review
    assert '3.0s into the potion' in window.alignment_notes[0]
    assert 'leaving 5.0s' in window.alignment_notes[0]
    actions = {**ACTIONS, 'Inner Release': {'description': ['Grants 2 stacks of Inner Release']}}
    assert not annotate(casts, (grant(3000),), begin=0, finish=8, actions=actions).alignment_notes


def test_followup_after_potion_is_reported_and_counts_are_preserved():
    casts = (cast(10000, 1), cast(11000, 2), cast(13500, 2), cast(16000, 2),
             cast(20000, 3), cast(22500, 4))
    window = annotate(casts, (grant(10000),), finish=21)
    assert 'after this potion' in action(window, 'Primal Ruination').notes[0]
    assert len(window.after_window_notes) == 1
    assert not window.before_window_notes
    assert action(window, 'Primal Ruination').expected == 0


def test_early_nc_requires_remaining_grant_lifetime_and_no_death_or_renewal():
    casts = (cast(8000, 6),)
    buffs = (grant(0, 1001897, 30000),)
    window = annotate(casts, buffs)
    assert '2.0s before this potion' in action(window, 'Nascent Chaos').notes[0]
    assert not annotate(casts, (grant(0, 1001897, 5000),)).alignment_notes
    assert not annotate(casts, buffs, life=(
        {'timestamp': 9000, 'type': 'death', 'targetID': 1},)).alignment_notes
    assert not annotate(casts, (*buffs, grant(9000, 1001897, 30000))).alignment_notes


def test_missing_activation_does_not_invent_a_sequence():
    assert not annotate((cast(1000, 2),)).alignment_notes


def test_late_potted_hit_does_not_warn_about_ir_overlap():
    casts = (cast(3000, 1), cast(4000, 2), cast(6500, 2), cast(9000, 5))
    damage = tuple({**e, 'type': 'damage', 'timestamp': e['timestamp'] + 1500,
                    'amount': 100, 'buffs': '1000049'} for e in casts if e['abilityGameID'] != 1)
    window = annotate(casts, (grant(3000),), begin=0, finish=8, damage=damage)
    assert not window.alignment_notes
    assert not any(a.review for a in window.actions)


def test_recorded_unpotted_hit_overrides_cast_inside_potion():
    casts = (cast(10000, 1), cast(11000, 2), cast(13500, 2), cast(16000, 2),
             cast(20000, 3), cast(20900, 4))
    damage = tuple({**e, 'type': 'damage', 'timestamp': e['timestamp'] + 1500,
                    'amount': 100, 'buffs': '' if e['abilityGameID'] == 4 else '1000049'}
                   for e in casts if e['abilityGameID'] != 1)
    window = annotate(casts, (grant(10000),), finish=21, damage=damage)
    assert action(window, 'Primal Ruination').review
    assert 'without a potion snapshot' in window.after_window_notes[0]
