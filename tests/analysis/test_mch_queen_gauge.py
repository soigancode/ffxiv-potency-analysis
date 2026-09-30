"""Unique damage fits replace an assumption; ambiguous fits preserve it."""

import pytest

from ffxiv_potency.analysis.mch.queen_gauge import infer_mch_opening_queen
from ffxiv_potency.analysis.models import PetDeploymentSummary


@pytest.mark.parametrize("amount,reference_amounts,expected", [
    (21600, (12600, 22800), 90),
    (15600, (12000, 24000), None),
])
def test_mch_opening_queen_requires_unique_damage_fit(amount, reference_amounts, expected):
    def hit(t, value, instance):
        return {"_time": t, "_name": "Arm Punch", "sourceID": 9,
                "sourceInstance": instance, "amount": value, "hitType": 1,
                "multiplier": 1}

    hits = [hit(5000, amount, 1), hit(6500, amount, 1),
            hit(25000, reference_amounts[0], 2), hit(45000, reference_amounts[1], 3)]
    deployments = (
        PetDeploymentSummary("Automaton Queen", 0, "Battery Gauge", 100, gauge_assumed=True),
        PetDeploymentSummary("Automaton Queen", 20, "Battery Gauge", 50),
        PetDeploymentSummary("Automaton Queen", 40, "Battery Gauge", 100),
    )
    actions = {"Arm Punch": {"potency": {"base": 120,
               "gauge_scaling": {"maximum_potency": 240}}}}
    result = infer_mch_opening_queen(hits, deployments, actions, 0, False)
    if expected is None:
        assert result == deployments
    else:
        assert result[0].gauge_spent == expected
        assert result[0].mch_gauge_inferred and not result[0].gauge_assumed
    assert result[1:] == deployments[1:]
    assert infer_mch_opening_queen(hits[:3], deployments[:2], actions, 0, False) == deployments[:2]
