"""Tests for profiles behavior."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import AnalysisError
from ffxiv_potency.analysis.profiles import _load_combat_profile


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")



def test_auto_attack_trait_comes_from_guide_not_combat_profile() -> None:
    actions = json.loads(
        (Path(__file__).parents[2] / "data/jobs/brd/7.4/actions.json").read_text(encoding="utf-8")
    )
    assert _load_combat_profile("bard").action_trait_multiplier == 1.2
    final_trait = next(
        trait for trait in actions["traits"] if trait["name"] == "Increased Action Damage II"
    )
    final_trait["action_damage_multiplier"] = 1.25
    assert _load_combat_profile("bard", actions).action_trait_multiplier == 1.25
    del final_trait["action_damage_multiplier"]
    with pytest.raises(AnalysisError, match="missing usable action damage trait"):
        _load_combat_profile("bard", actions)

