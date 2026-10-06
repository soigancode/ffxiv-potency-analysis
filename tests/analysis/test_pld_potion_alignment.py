"""PLD potion placement uses recorded bursts without changing package scores."""

from ffxiv_potency.analysis.burst_opportunities import BurstAction, BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.pld.potion_alignment import annotate_potion_alignment

NAMES = {1: 'Imperator', 2: 'Confiteor', 3: 'Blade of Faith', 4: 'Blade of Truth',
         5: 'Blade of Valor', 6: 'Blade of Honor', 7: 'Goring Blade', 8: 'Expiacion'}


def cast(time, ability, source=1):
    return {'timestamp': time, 'abilityGameID': ability, 'packetID': time,
            'sourceID': source, 'type': 'cast'}


def annotate(casts, *, windows=((0, 20000, 1.25),), begin=10, finish=40,
             damage=(), buffs=(), life=()):
    window = BurstWindow(begin, finish, tuple(BurstAction(name, 0, 0, 0)
                                             for name in NAMES.values()), 1000, 1000, 1000)
    return annotate_potion_alignment(window, casts, damage, NAMES, 1, 0, 120000,
                                     windows, 1000049, buffs, life)


def action(window, name):
    return next(a for a in window.actions if a.name == name)


def test_early_actions_mark_zero_expected_cells_and_preserve_cached_scores():
    window = annotate((cast(1000, 1), cast(3500, 2), cast(6000, 3),
                       cast(11000, 4), cast(13500, 5), cast(14500, 6)))
    assert action(window, 'Confiteor').review
    assert not action(window, 'Blade of Honor').review
    assert '6.5s before its start' in action(window, 'Confiteor').notes[0]
    assert window.before_window_notes[-1] == 'Fight or Flight started 10.0s before the potion.'
    assert window.actual_package_potency == window.best_package_potency == 1000
    assert _decode(_encode(window), BurstWindow) == window


def test_delayed_chain_is_associated_but_normal_between_burst_cooldown_is_not():
    window = annotate((cast(1000, 1), cast(11000, 2), cast(15000, 3), cast(18000, 4),
                       cast(22000, 5), cast(42000, 6), cast(45000, 8)))
    assert action(window, 'Blade of Honor').review
    assert '2.0s after its end' in window.after_window_notes[0]
    assert not action(window, 'Expiacion').review


def test_selects_current_burst_instead_of_previous_held_followup():
    window = annotate((cast(1000, 1), cast(54000, 6), cast(61000, 1), cast(63500, 2),
                       cast(66000, 3), cast(68500, 4), cast(71000, 5), cast(72000, 6)),
                      windows=((0, 20000, 1.25), (60000, 80000, 1.25)), begin=53, finish=83)
    assert not window.alignment_notes


def test_potted_snapshot_exempts_cast_before_buff_boundary_and_ignores_other_players():
    window = annotate((cast(9000, 1), cast(9900, 2), cast(1000, 3, source=2)),
                      windows=((9000, 29000, 1.25),), damage=(
                          {**cast(9900, 2), 'timestamp': 11000, 'type': 'damage',
                           'buffs': '1000049', 'amount': 100},))
    assert not action(window, 'Confiteor').review
    assert not action(window, 'Blade of Faith').review


def test_late_buff_end_does_not_warn_when_all_actions_fit():
    window = annotate((cast(12000, 1), cast(14000, 2)),
                      windows=((11000, 31000, 1.25),), finish=30)
    assert not window.after_window_notes
    assert not any(a.review for a in window.actions)


def test_potted_application_landing_after_potion_end_does_not_warn_about_buff_end():
    application = cast(29900, 8)
    damage = ({**application, 'type': 'damage', 'timestamp': 30500,
               'amount': 100, 'buffs': '1000049'},
              {**application, 'type': 'damage', 'timestamp': 34000,
               'amount': 30, 'tick': True, 'buffs': '1000049'})
    window = annotate((cast(12000, 1), application), finish=30,
                      windows=((11000, 31000, 1.25),), damage=damage)
    assert not window.alignment_notes


def test_unpotted_snapshot_is_flagged_even_when_cast_is_inside_potion():
    event = cast(29900, 8)
    window = annotate((cast(12000, 1), event), finish=30,
        windows=((11000, 31000, 1.25),), damage=(
            {**event, 'type': 'damage', 'timestamp': 30500, 'amount': 100, 'buffs': ''},))
    assert action(window, 'Expiacion').review
    assert 'without a potion snapshot' in window.after_window_notes[0]
    assert window.after_window_notes[-1] == 'Fight or Flight ended 1.0s after the potion.'


def test_unpotted_filler_or_auto_hit_still_marks_buff_overlap():
    extra = {**cast(30500, 99), 'type': 'damage', 'amount': 100,
             'buffs': '1000076'}
    window = annotate((cast(12000, 1), cast(14000, 2)), finish=30,
                      windows=((11000, 31000, 1.25),), damage=(extra,))
    assert '1 other landed hit during Fight or Flight lacked a potion snapshot.' in window.after_window_notes
    assert window.after_window_notes[-1] == 'Fight or Flight ended 1.0s after the potion.'


def test_delayed_goring_requires_recorded_grant_and_cannot_be_carried_through_death():
    casts = (cast(1000, 1), cast(26000, 7))
    grant = {'timestamp': 0, 'type': 'applybuff', 'targetID': 1,
             'abilityGameID': 1003847, 'duration': 30000}
    assert action(annotate(casts, finish=25, buffs=(grant,)), 'Goring Blade').review
    assert not action(annotate(casts, finish=25), 'Goring Blade').review
    assert not action(annotate(casts, finish=25, buffs=(grant,), life=(
        {'timestamp': 24000, 'type': 'death', 'targetID': 1},)), 'Goring Blade').review


def test_no_related_buff_does_not_invent_alignment():
    assert not annotate((cast(1000, 1),), windows=()).alignment_notes


def test_missing_packet_ids_do_not_merge_separate_casts_or_share_potion_snapshots():
    casts = ({**cast(1000, 8), 'packetID': None}, {**cast(5000, 8), 'packetID': None})
    damage = ({**cast(15000, 8), 'packetID': None, 'buffs': '1000049'},)
    window = annotate(casts, damage=damage)
    assert '2 Expiacion used before the potion' in action(window, 'Expiacion').notes[0]
