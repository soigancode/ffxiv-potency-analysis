"""Extended Blade comparisons preserve grants, charge expiry and future actions."""

from copy import deepcopy
from dataclasses import replace

from test_pld_cleaves import example

from ffxiv_potency.analysis.burst_opportunities import BurstWindow
from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.pld.holds import compare_holds
from ffxiv_potency.analysis.targetability import TargetableTime
from ffxiv_potency.reporting import hold_comparison_note


def run_example(change=None, *, fixture=None, life=(), target_windows=None):
    window, original = example() if fixture is None else fixture
    args = deepcopy(original)
    casts, hits, rows, names, actions, source, start, _, self_windows, buffs, debuffs, combatants, profile, penalties = args
    # Truth -> Valor must remain within the separate 30s combo timer.
    casts[-2]['timestamp'] = 35000
    buffs[0]['timestamp'] = 35000
    names[7] = 'Guardian'
    names[6] = 'Holy Circle'
    names[8] = 'Clemency'
    casts.append({'type': 'cast', 'sourceID': 1, 'abilityGameID': 7,
                  'timestamp': 35670, 'packetID': 77})
    if change:
        change(casts, hits, buffs)
    return compare_holds((window,), casts, hits, rows, names, actions, source, start, 120000,
        TargetableTime(120, 'test', ((0, 120000),)), list(life), buffs, debuffs, combatants,
        self_windows, profile, penalties, target_windows)[0]


def test_joint_hold_wins_despite_unenhanced_valor_loss():
    window = run_example()
    comparison = window.hold_comparison
    assert comparison is not None
    assert comparison.inside_potency == 2500
    assert comparison.recorded_potency == 2590
    assert comparison.proposed_potency == 2590
    assert [a.name for a in comparison.actions] == ['Blade of Valor', 'Blade of Honor']
    assert [a.cast_seconds for a in comparison.actions] == [35, 50]
    assert _decode(_encode(window), BurstWindow) == window
    note = hold_comparison_note(window, str)
    assert 'Action | Inside FoF | Held' in note
    assert 'Total | 2,500.0 | 2,590.0' in note
    assert 'Holding gained 90.0 potency.' in note


def test_inside_mitigation_with_null_potency_keeps_its_weave_slot():
    window, args = example()
    window = replace(window, proposed_order=(*window.proposed_order, ('Guardian', 3)))
    result = run_example(fixture=(window, args))
    assert result.hold_comparison is not None
    assert ('Guardian', 3) in result.proposed_order


def test_insufficient_targets_without_req_cannot_win():
    def change(casts, hits, buffs):
        buffs[-1]['timestamp'] = 100000  # No later potion.
    window = run_example(change)
    comparison = window.hold_comparison
    assert comparison is not None
    assert comparison.proposed_potency == 2500
    assert [a.targets for a in comparison.actions] == [1, 1]
    assert 'Recorded | Proposed' in hold_comparison_note(window, str)


def test_expired_combo_cannot_be_proposed_even_when_recorded_hits_exist():
    def change(casts, hits, buffs):
        next(e for e in casts if e['abilityGameID'] == 4)['timestamp'] = 40000  # 33s after proposed Truth.
        buffs[0]['timestamp'] = 40000
    window = run_example(change)
    assert window.hold_comparison is not None
    assert window.hold_comparison.proposed_potency == 2500


def test_expired_honor_cannot_use_the_next_buff():
    def change(casts, hits, buffs):
        next(e for e in casts if e['abilityGameID'] == 5)['timestamp'] = 66000  # More than 30s after Valor.
    window = run_example(change)
    assert window.hold_comparison is not None
    assert window.hold_comparison.proposed_potency == 2500


def test_future_recorded_gcd_prevents_hypothetical_aoe_replacement():
    def change(casts, hits, buffs):
        # The witnessed AoE slot belongs to a future Holy Circle. Holding
        # Truth cannot replace it while claiming its resource use is preserved.
        casts.append({'type': 'cast', 'sourceID': 1, 'abilityGameID': 6,
                      'timestamp': 25000, 'packetID': 99})
        hits.extend({'type': 'damage', 'sourceID': 1, 'abilityGameID': 6,
                     'timestamp': 25500, 'packetID': 99, 'targetID': target, 'amount': 100}
                    for target in (2, 3))
    result = run_example(change)
    assert result.hold_comparison is not None
    assert dict(result.proposed_order)['Blade of Truth'] == 7


def test_fixed_inside_spell_consumes_a_requiescat_charge():
    def change(casts, hits, buffs):
        casts.append({'type': 'cast', 'sourceID': 1, 'abilityGameID': 8,
                      'timestamp': 1300, 'packetID': 88})
    comparison = run_example(change).hold_comparison
    assert comparison is not None
    valor = next(a for a in comparison.actions if a.name == 'Blade of Valor')
    assert valor.inside_potency == 625  # The fourth Blade no longer has a charge.


def test_death_invalidates_a_held_chain():
    comparison = run_example(life=({'type': 'death', 'targetID': 1, 'timestamp': 30000},)).hold_comparison
    assert comparison is not None
    assert comparison.proposed_potency == 2500


def test_target_cutoff_prevents_a_two_target_hold():
    comparison = run_example(target_windows={
        (2, 1): ((0, 120000),), (3, 1): ((0, 34000),),
    }).hold_comparison
    assert comparison is not None
    assert comparison.proposed_potency == 2500


def test_next_imperator_cannot_supply_old_blades_with_new_charges():
    window, args = example()
    args[3][9] = 'Imperator'
    def change(casts, hits, buffs):
        casts.append({'type': 'cast', 'sourceID': 1, 'abilityGameID': 9,
                      'timestamp': 34000, 'packetID': 90})
    comparison = run_example(change, fixture=(window, args)).hold_comparison
    assert comparison is not None
    valor = next(a for a in comparison.actions if a.name == 'Blade of Valor')
    assert valor.proposed_potency == 700
    assert valor.enhancement == 'None'


def test_two_target_truth_can_win_while_requiescat_is_still_active():
    window, args = example()
    window = replace(window, proposed_order=(('Imperator', 10), ('Confiteor', 11),
        ('Blade of Faith', 13.5), ('Blade of Truth', 16),
        ('Blade of Valor', 18.5), ('Blade of Honor', 19.2)))
    truth = next(e for e in args[0] if e['abilityGameID'] == 3)
    truth['timestamp'] = 22000
    for target, value in ((2, 880), (3, 352)):
        hit = {**truth, 'type': 'damage', 'targetID': target, 'amount': 100}
        args[1].append(hit)
        args[2].append((hit, hit['timestamp'], 'Blade of Truth', value))
    result = run_example(fixture=(window, args))
    comparison = result.hold_comparison
    assert comparison is not None
    truth = next(a for a in comparison.actions if a.name == 'Blade of Truth')
    assert truth.cast_seconds == 22
    assert truth.enhancement == 'Requiescat'
    assert truth.inside_potency == 1100
    assert truth.proposed_potency == 1232


def test_single_target_windows_exit_without_a_hold_search():
    window, args = example()
    casts, hits, rows, names, actions, source, start, _, self_windows, buffs, debuffs, combatants, profile, penalties = args
    hits = [h for h in hits if h['targetID'] == 2]
    result = compare_holds((window,), casts, hits, rows, names, actions, source, start, 120000,
        TargetableTime(120, 'test', ((0, 120000),)), [], buffs, debuffs, combatants,
        self_windows, profile, penalties)
    assert result == (window,)


def test_unknown_targetability_remains_unscored():
    window = run_example()
    original = replace(window, hold_comparison=None)
    assert compare_holds((original,), [], [], [], {}, {}, 1, 0, 120000,
                         None, [], [], [], [], {}, None, {}) == (original,)
