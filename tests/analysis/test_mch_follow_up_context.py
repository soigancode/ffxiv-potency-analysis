"""MCH context distinguishes early detonation and independent pet lifetimes."""

from types import SimpleNamespace

from ffxiv_potency.analysis.mch.diagnostics import sequence_context
from ffxiv_potency.analysis.mch.wildfire import MchWildfireSummary
from ffxiv_potency.analysis.models import PetDeploymentSummary
from ffxiv_potency.analysis.targetability import TargetableTime


def queen_context(end=40000, life=(), intervals=((0, 40000),), reasons=()):
    queen = PetDeploymentSummary('Automaton Queen', 0, 'Battery Gauge', 50,
                                 mch_missing_finishers=('Pile Bunker', 'Crowned Collider'))
    result = SimpleNamespace(mch_wildfires=(), pet_deployments=(queen,), ghosted_ending_times=reasons)
    return sequence_context(result, life, 1, 0, end, TargetableTime(end / 1000, 'events', intervals))


def test_player_death_does_not_end_a_queen_deployment():
    rows = queen_context(life=({'type': 'death', 'targetID': 1, 'timestamp': 5000},))
    assert rows[0].reason == 'reason unconfirmed'


def test_queen_downtime_and_fight_end_are_bounded_by_its_active_duration():
    assert queen_context(intervals=((0, 5000), (15000, 40000)))[0].reason == 'boss downtime during deployment'
    assert queen_context(end=5000, intervals=((0, 5000),))[0].reason == 'fight ended during deployment'
    assert queen_context(intervals=((0, 5000), (10000, 40000)))[0].reason == 'reason unconfirmed'


def test_queen_finishers_retain_recorded_hp_lock_reason():
    assert queen_context(reasons=(('Pile Bunker', ((11, 'phase HP lock'),)),))[0].reason == 'phase HP lock'


def test_wildfire_early_detonation_is_distinct_from_death_and_fight_end():
    window = MchWildfireSummary(0, 5, 3, 720, detonated_early=True)
    result = SimpleNamespace(mch_wildfires=(window,), pet_deployments=())
    rows = sequence_context(result, [{'type': 'death', 'targetID': 1, 'timestamp': 4000}],
                            1, 0, 6000, TargetableTime(6, 'events', ((0, 6000),)))
    assert rows[0].reason == 'detonated early'
    assert rows[0].actions == ('Wildfire: 3/6 landed GCDs',)
