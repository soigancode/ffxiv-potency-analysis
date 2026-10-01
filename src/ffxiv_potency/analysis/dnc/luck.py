"""Standardized proc-luck indices, with bounds for invisible Feather rolls."""

from math import sqrt
from statistics import NormalDist
from typing import Any

from ..events import _event_name
from ..models import DncReadyProcSummary
from .ready_procs import FAMILIES


def score(excess: float, variance: float) -> float | None:
    """A normal-reference index: average=50, not an exact percentile or probability."""
    return 100 * NormalDist().cdf(excess / sqrt(variance)) if variance > 0 else None


def proc_luck(
    ready: tuple[DncReadyProcSummary, ...],
    rules: dict[str, tuple[str, float]],
    feather_events: list[dict[str, Any]],
    abilities: dict[int, str],
    successes_min: int | None,
    successes_max: int | None,
) -> tuple[float | None, float | None, float | None, float | None]:

    initial_excess = initial_variance = weighted_excess = weighted_variance = 0.0
    initial_known = True
    for stage in ready[:2]:
        if stage.random_grants is None or stage.random_grants > sum(
            count for _, count in stage.trials
        ):
            initial_known = False
            break
        variance = sum(
            count * rules[name][1] * (1 - rules[name][1]) for name, count in stage.trials
        )
        excess = stage.random_grants - stage.expected
        initial_excess += excess
        initial_variance += variance
        rates = {rules[name][1] for name in FAMILIES[stage.name][2] if name in rules}
        if len(rates) != 1:
            initial_known = False
            break
        weight = rates.pop()
        weighted_excess += weight * excess
        weighted_variance += weight * weight * variance
    feather_expected = sum(rules[_event_name(e, abilities)][1] for e in feather_events)
    feather_variance = sum(
        rules[_event_name(e, abilities)][1] * (1 - rules[_event_name(e, abilities)][1])
        for e in feather_events
    )
    minimum = maximum = None
    if initial_known and successes_min is not None and successes_max is not None:
        variance = weighted_variance + feather_variance
        minimum = score(weighted_excess + successes_min - feather_expected, variance)
        maximum = score(weighted_excess + successes_max - feather_expected, variance)
    threefold = ready[2]
    fan_variance = sum(
        count * rules[name][1] * (1 - rules[name][1]) for name, count in threefold.trials
    )
    return (
        score(initial_excess, initial_variance) if initial_known else None,
        minimum,
        maximum,
        score(threefold.random_grants - threefold.expected, fan_variance)
        if (
            threefold.random_grants is not None
            and threefold.random_grants <= sum(count for _, count in threefold.trials)
        )
        else None,
    )


def combined_feather_luck(
    ready: tuple[DncReadyProcSummary, ...],
    feather_trials: int,
    feather_successes_min: int | None,
) -> float | None:
    """Geometric mean of observed rates, using the supported Feather minimum."""
    if len(ready) != 3 or feather_successes_min is None:
        return None
    initial_trials = initial_successes = 0
    for stage in ready[:2]:
        trials = sum(count for _, count in stage.trials)
        if stage.random_grants is None or not 0 <= stage.random_grants <= trials:
            return None
        initial_trials += trials
        initial_successes += stage.random_grants
    fan_trials = sum(count for _, count in ready[2].trials)
    fan_successes = ready[2].random_grants
    if (
        min(initial_trials, feather_trials, fan_trials) <= 0
        or not 0 <= feather_successes_min <= feather_trials
        or fan_successes is None
        or not 0 <= fan_successes <= fan_trials
    ):
        return None
    product = (
        initial_successes
        / initial_trials
        * feather_successes_min
        / feather_trials
        * fan_successes
        / fan_trials
    )
    return 100 * product ** (1 / 3)
