"""Independent alignment arithmetic, packet grouping and expected hit bonuses."""

from dataclasses import replace

import pytest

from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.cooldown_timing import CooldownTiming
from ffxiv_potency.analysis.diagnostic_types import FollowUpContext
from ffxiv_potency.analysis.diagnostics import summarize_alignment
from ffxiv_potency.analysis.models import AnalysisResult
from ffxiv_potency.analysis.profiles import _load_combat_profile
from ffxiv_potency.reporting import (
    print_burst_alignment,
    print_cooldown_timing,
    print_follow_up_context,
)


def event(packet=1, buffs='', target=2):
    return {'type': 'damage', 'sourceID': 1, 'targetID': target, 'packetID': packet,
                'abilityGameID': 2, 'buffs': buffs}


def test_bard_damage_snapshot_groups_ticks_and_targets_once():
    profile = _load_combat_profile('bard')
    rows = [(event(buffs='10'), 1000, 'Stormbite', 115),
            (event(buffs='10', target=3), 1000, 'Stormbite', 115),
            (event(2), 25000, 'Stormbite', 100),
            (event(2), 25000, 'Stormbite', 100)]
    result = summarize_alignment('bard', rows, [], {10: 'Raging Strikes'}, 1, 0, 60000,
                                 {10: ((0, 20000, 1.15),)}, profile, set())[0]
    assert result.inside_potency == pytest.approx(200)
    assert result.outside_potency == 200
    assert result.outside[0].uses == 1
    assert result.outside[0].potential_gain == pytest.approx(30)
    assert result.windows[0].inside_potency == pytest.approx(200)


def test_dancer_technical_gain_uses_recorded_finish_strength():
    rows = [(event(buffs='10'), 1000, 'Saber Dance', 103),
            (event(2), 25000, 'Saber Dance', 100)]
    result = summarize_alignment('dancer', rows, [], {10: 'Technical Finish'}, 1, 0, 60000,
                                 {10: ((0, 20000, 1.03),)}, _load_combat_profile('dancer'), set())[0]
    assert result.inside_potency == pytest.approx(100)
    assert result.outside[0].potential_gain == pytest.approx(3)


@pytest.mark.parametrize('job,status,action,kind', [
    ('machinist', 'Reassembled', 'Drill', 'guaranteed'),
    ('dancer', 'Devilment', 'Saber Dance', 'rate'),
])
def test_rate_and_guaranteed_gains_are_damage_equivalents_not_potency_buffs(job, status, action, kind):
    profile = replace(_load_combat_profile(job), critical_rate=.2, direct_rate=.1,
                      critical_damage_multiplier=1.6, guaranteed_direct_multiplier=1.1)
    buff = {'type': 'applybuff', 'abilityGameID': 10, 'sourceID': 1, 'targetID': 1,
                'timestamp': 0, 'duration': 20000}
    rows = [(event(buffs='10'), 1000, action, 100), (event(2), 25000, action, 100)]
    result = next(r for r in summarize_alignment(job, rows, [buff], {10: status}, 1, 0,
                  60000, {}, profile, {(1, 2)} if job == 'machinist' else set()) if r.kind == kind)
    baseline = (1 + .2 * .6) * (1 + .1 * .25)
    expected = (1.6 * 1.25 * 1.1 - baseline if kind == 'guaranteed'
                else (1 + .4 * .6) * (1 + .3 * .25) - baseline)
    assert result.inside_potency == result.outside_potency == 100
    assert result.outside[0].potential_gain == pytest.approx(100 * expected)


def test_absent_status_windows_are_unavailable_even_if_an_attack_has_a_buff_flag(capsys):
    alignment = summarize_alignment('bard', [(event(), 0, 'Apex Arrow', 100)], [],
                                    {}, 1, 0, 60000, {}, _load_combat_profile('bard'), set())
    assert not alignment[0].evidence_available
    print_burst_alignment(alignment, str)
    assert 'unavailable (no recorded buff windows)' in capsys.readouterr().out


def test_rendering_has_consistent_precision_indentation_and_explicit_timestamp_labels(capsys):
    print_cooldown_timing((CooldownTiming('Drill', 3.25, 2.5),))
    print_follow_up_context((FollowUpContext(1, ('Excavator',), 'cast, no hit', 'phase HP lock'),), str)
    output = capsys.readouterr().out
    assert '\n  Cooldown timing:\n' in output
    assert '3.2s' in output and '2.5s' in output
    assert '    Cast 1: Excavator cast, no hit - phase HP lock' in output
    assert output.isascii()


def test_result_model_declares_concrete_cache_types():
    from typing import get_type_hints

    from ffxiv_potency.analysis.combos import ComboSummary
    from ffxiv_potency.analysis.diagnostic_types import BurstAlignment

    hints = get_type_hints(AnalysisResult)
    assert hints['burst_alignment'] == tuple[BurstAlignment, ...]
    assert hints['combos'] == ComboSummary | None
    row = FollowUpContext(1, ('Excavator',), 'missing', 'fight ended during sequence')
    assert _decode(_encode(row), FollowUpContext) == row


def test_inferred_multi_target_break_is_one_report_line_with_summed_loss(capsys):
    from ffxiv_potency.analysis.combos import ComboInference, ComboSummary
    from ffxiv_potency.reporting import print_combo_diagnostics

    rows = (ComboInference('Bladeshower', 1, False, 100, 60, 5, 'Saber Dance', 10),
            ComboInference('Bladeshower', 1.1, False, 100, 60, 6, 'Saber Dance', 10))
    print_combo_diagnostics(ComboSummary((), inferred=rows), str)
    output = capsys.readouterr().out
    assert output.count('-> Bladeshower') == 1
    assert '120.0 estimated base potency lost' in output and '2 landed hits' in output
