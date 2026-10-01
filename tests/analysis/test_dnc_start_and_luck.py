"""Reset policy, conservative checkpoint handling, and descriptive luck indices."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis.dnc.luck import score
from ffxiv_potency.analysis.dnc.procs import summarize_dnc_procs
from ffxiv_potency.analysis.dnc.starting_gauge import starting_feathers

ACTIONS = {
    a["name"]: a for a in json.loads(Path("data/jobs/dnc/7.4/actions.json").read_text())["actions"]
}
NAMES = {1: "Reverse Cascade", 2: "Fan Dance"}


@pytest.mark.parametrize("encounter", [101, 102, 103, 104, 1083, 1084, 1085])
def test_fresh_raid_and_trial_pulls_start_empty(tmp_path, encounter):
    assert starting_feathers(tmp_path, {"encounterID": encounter}, 1)[0] == (0,)


@pytest.mark.parametrize("encounter", [4549, 4550, 4551])
def test_full_dungeon_and_criterion_runs_start_empty(tmp_path, encounter):
    assert starting_feathers(tmp_path, {"encounterID": encounter}, 1)[0] == (0,)


def test_checkpoint_wipe_resets_but_carry_and_missing_context_remain_bounded(tmp_path):
    fight = {"encounterID": 105, "id": 10, "startTime": 5000}
    path = tmp_path / "checkpoint-context.json"
    assert starting_feathers(tmp_path, fight, 1)[0] == (0, 1, 2, 3, 4)
    path.write_text(json.dumps({"carry": False}))
    assert starting_feathers(tmp_path, fight, 1)[0] == (0,)
    context = {
        "carry": True,
        "fightID": 10,
        "sourceID": 1,
        "previousFight": {"encounterID": 104, "kill": True, "endTime": 4000},
    }
    path.write_text(json.dumps(context))
    assert starting_feathers(tmp_path, fight, 1) == ((0, 1, 2, 3, 4), "phase-one carry-over")
    for bad in [
        context | {"sourceID": 2},
        context | {"fightID": 9},
        context | {"previousFight": {"encounterID": 104, "kill": False, "endTime": 4000}},
        {"carry": False, "fightID": 9},
    ]:
        path.write_text(json.dumps(bad))
        assert starting_feathers(tmp_path, fight, 1) == (
            (0, 1, 2, 3, 4),
            "checkpoint carry-over unknown",
        )


def test_zero_start_exposes_missing_gains_instead_of_inventing_starting_feathers():
    spend = {
        "timestamp": 100,
        "packetID": 1,
        "type": "cast",
        "sourceID": 1,
        "targetID": 10,
        "abilityGameID": 2,
    }
    unknown = summarize_dnc_procs([spend], [], [], [], NAMES, ACTIONS, 1)
    empty = summarize_dnc_procs([spend], [], [], [], NAMES, ACTIONS, 1, starting_feathers=(0,))
    assert unknown.feathers_gained_min == 0
    assert empty.feathers_gained_min is None
    assert empty.feather_luck_min is None


def test_score_is_centred_symmetric_and_standardized_for_variation():
    assert score(0, 25) == 50
    assert score(5, 25) == pytest.approx(84.1344746)
    assert score(50, 2500) == score(5, 25)
    lower, upper = score(-5, 25), score(5, 25)
    assert lower is not None and upper is not None
    assert lower + upper == pytest.approx(100)
    assert score(0, 0) is None


def test_unknown_and_zero_variance_rolls_do_not_get_a_fabricated_luck_score():
    empty = summarize_dnc_procs([], [], [], [], NAMES, ACTIONS, 1, starting_feathers=(0,))
    assert empty.initial_proc_luck is None
    assert empty.feather_luck_min is None
    assert empty.threefold_luck is None
    hit = {
        "timestamp": 100,
        "packetID": 1,
        "type": "calculateddamage",
        "sourceID": 1,
        "targetID": 10,
        "abilityGameID": 1,
        "amount": 100,
        "hitType": 1,
    }
    missing = summarize_dnc_procs([], [hit], None, [], NAMES, ACTIONS, 1, starting_feathers=(0,))
    assert missing.feather_luck_min is None
    assert missing.initial_proc_luck is None


def test_feather_chain_luck_is_separate_from_threefold_luck():
    from dataclasses import replace

    from ffxiv_potency.analysis.dnc.luck import proc_luck
    from ffxiv_potency.analysis.models import DncReadyProcSummary

    def stage(name, action):
        return DncReadyProcSummary(name, ((action, 4),), 2, 2, 0, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0)

    ready = (
        stage("Symmetry", "Cascade"),
        stage("Flow", "Fountain"),
        stage("Threefold", "Fan Dance"),
    )
    rules = {
        "Cascade": ("Silken Symmetry", 0.5),
        "Fountain": ("Silken Flow", 0.5),
        "Reverse Cascade": ("a Fourfold Feather", 0.5),
        "Fountainfall": ("a Fourfold Feather", 0.5),
        "Fan Dance": ("Threefold Fan Dance", 0.5),
    }
    hits = [{"abilityGameID": 1} for _ in range(4)]
    neutral = proc_luck(ready, rules, hits, NAMES, 2, 2)
    assert neutral[1:3] == (50, 50)
    assert neutral[3] == 50
    lucky_fans = proc_luck(
        ready[:2] + (replace(ready[2], random_grants=3),), rules, hits, NAMES, 2, 2
    )
    assert lucky_fans[1:3] == neutral[1:3]
    assert lucky_fans[3] is not None and lucky_fans[3] > 50
    unlucky = proc_luck(ready[:2] + (replace(ready[2], random_grants=1),), rules, hits, NAMES, 2, 2)
    assert unlucky[3] is not None and unlucky[3] < 50
    missing = proc_luck(
        ready[:2] + (replace(ready[2], random_grants=None),), rules, hits, NAMES, 2, 2
    )
    assert missing[3] is None
    assert missing[1:3] == neutral[1:3]


@pytest.mark.parametrize("successes,expected", [(0, 0), (4, 50), (6, 75), (8, 100)])
def test_combined_feather_score_uses_rates_not_rarity(successes, expected):
    from ffxiv_potency.analysis.dnc.luck import combined_feather_luck
    from ffxiv_potency.analysis.models import DncReadyProcSummary

    def stage(name, action, scale):
        return DncReadyProcSummary(
            name,
            ((action, 8 * scale),),
            4 * scale,
            successes * scale,
            100,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )

    for scale in (1, 10):
        ready = (
            stage("Symmetry", "Cascade", scale),
            stage("Flow", "Fountain", scale),
            stage("Threefold", "Fan Dance", scale),
        )
        assert combined_feather_luck(ready, 8 * scale, successes * scale) == pytest.approx(expected)


def test_combined_feather_score_includes_threefold_and_handles_missing_evidence():
    from dataclasses import replace

    from ffxiv_potency.analysis.dnc.luck import combined_feather_luck
    from ffxiv_potency.analysis.models import DncReadyProcSummary

    def stage(name, action, trials, grants):
        return DncReadyProcSummary(
            name, ((action, trials),), trials / 2, grants, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        )

    ready = (
        stage("Symmetry", "Cascade", 29, 14),
        stage("Flow", "Fountain", 27, 13),
        stage("Threefold", "Fan Dance", 31, 17),
    )
    actual = combined_feather_luck(ready, 43, 31)
    assert actual == pytest.approx(100 * (27 / 56 * 31 / 43 * 17 / 31) ** (1 / 3))
    assert actual is not None and round(actual, 1) == 57.6
    better = combined_feather_luck(ready[:2] + (replace(ready[2], random_grants=24),), 43, 31)
    assert better is not None and better > actual
    assert combined_feather_luck(ready, 43, None) is None
    assert combined_feather_luck(ready, 43, 44) is None
    assert combined_feather_luck(ready[:2], 43, 31) is None
    for missing in [
        replace(ready[2], random_grants=None),
        replace(ready[2], trials=(), random_grants=0),
        replace(ready[2], random_grants=32),
    ]:
        assert combined_feather_luck(ready[:2] + (missing,), 43, 31) is None
    assert (
        combined_feather_luck((replace(ready[0], random_grants=None),) + ready[1:], 43, 31) is None
    )
