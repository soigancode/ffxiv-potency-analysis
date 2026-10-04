"""Per-window potion attribution preserves snapshots, ranges and cache types."""

from dataclasses import replace

from ffxiv_potency.analysis.cache import _decode, _encode
from ffxiv_potency.analysis.models import PotionSummary, PotionWindow, PotionWindowTotal
from ffxiv_potency.analysis.potion import summarize_potion_windows


def test_snapshot_tail_belongs_to_first_window_and_ranges_sum_without_rounding():
    windows = (PotionWindow(-2, 28), PotionWindow(40, 70), PotionWindow(80, 100))
    # The row timestamp is the application snapshot, not the later landing time.
    totals = summarize_potion_windows(windows, [
        (27, 100, 160, 8, 12.8), (29, 50, 50, 4, 4), (41, 200, 200, 16, 16),
    ])
    assert totals == (PotionWindowTotal(150, 210, 12, 16.8),
                      PotionWindowTotal(200, 200, 16, 16), PotionWindowTotal(0, 0, 0, 0))
    potion = PotionSummary(3, 350, 410, 28, 32.8, windows, window_totals=totals)
    assert _decode(_encode(potion), PotionSummary) == potion


def test_unknown_window_boundaries_are_retained_with_recorded_hit_totals():
    windows = (PotionWindow(None, None, 4, 20, True), PotionWindow(300, 330))
    totals = summarize_potion_windows(windows, [(2, 100, 100, 9, 9), (310, 50, 50, 5, 5)])
    assert totals == (PotionWindowTotal(100, 100, 9, 9), PotionWindowTotal(50, 50, 5, 5))
    assert windows[0].start_seconds is None and windows[0].end_seconds is None


def test_empty_contributions_keep_zero_use_windows():
    assert summarize_potion_windows((PotionWindow(0, 30),), []) == (
        PotionWindowTotal(0, 0, 0, 0),)
    assert summarize_potion_windows((), []) == ()


def test_rendering_has_table_totals_and_explanation_together_with_ranges(capsys):
    from ffxiv_potency.cli import _print_analysis
    from tests.cli.test_execution_losses import result_with_losses

    potion = PotionSummary(1, 100, 160, 8, 12.8, (PotionWindow(-2, 28),),
                           window_totals=(PotionWindowTotal(100, 160, 8, 12.8),))
    _print_analysis(replace(result_with_losses('pld'), potion=potion))
    output = capsys.readouterr().out.split('Potions:\n')[1].split('\nHit Bonus and Luck:')[0]
    assert 'Start' in output and 'End' in output and 'Landed base potency' in output
    assert '-00m02s' in output and '00m28s' in output
    assert '100.0-160.0' in output
    assert 'Window 1:' not in output
    assert '\n  Potted base potency: 100.0-160.0 | Potency gained: 8.0-12.8' in output
    assert '\n  Potency includes all landed damage and auto-attacks with a potion snapshot.' in output
    assert '\n\n  Potted base potency:' not in output
