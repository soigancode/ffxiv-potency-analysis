"""Raid Crit/DH effects in FF Logs adjust expected luck."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis.luck import _load_raid_effects, _raid_luck_adjustment
from ffxiv_potency.analysis.profiles import _load_combat_profile
from ffxiv_potency.raid_effects import resolve_effects


def test_target_debuff_and_player_buffs_adjust_expected_luck() -> None:
    profile = _load_combat_profile("machinist")
    effects = json.loads(
        (Path(__file__).parents[2] / "data/raid_effects/7.4.json").read_text()
    )
    effects = resolve_effects(effects, Path("data"), "7.55")
    names = {
        1: "Battle Litany",
        2: "Battle Voice",
        3: "Army's Paeon",
        4: "The Wanderer's Minuet",
        5: "Chain Stratagem",
        6: "Devilment",
    }
    assert _raid_luck_adjustment({"buffs": ""}, effects, names, profile) == 0
    assert _raid_luck_adjustment({"buffs": "5."}, effects, names, profile) == pytest.approx(
        0.10 * (profile.critical_damage_multiplier - 1) * (1 + profile.direct_rate * 0.25)
    )
    assert _raid_luck_adjustment({"buffs": "1.2.3.4.5."}, effects, names, profile) > 0.10
    crit_strength = profile.critical_damage_multiplier - 1
    buffed = _raid_luck_adjustment({"buffs": "6."}, effects, names, profile)
    expected = (1 + (profile.critical_rate + 0.20) * crit_strength) * (
        1 + (profile.direct_rate + 0.20) * 0.25
    ) - (1 + profile.critical_rate * crit_strength) * (1 + profile.direct_rate * 0.25)
    assert buffed == pytest.approx(expected)


def test_old_local_effects_fall_back_to_complete_bundled_data(tmp_path: Path) -> None:
    actions = tmp_path / "data/jobs/mch/7.4/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"patch": "7.55"}', encoding="utf-8")
    existing = tmp_path / "data/raid_buffs/7.55/effects.json"
    existing.parent.mkdir(parents=True)
    bundled = json.loads(
        (Path(__file__).parents[2] / "data/raid_effects/7.4.json").read_text()
    )
    bundled["effects"] = resolve_effects(bundled, Path("data"), "7.55")
    existing.write_text(
        json.dumps({
            "patch": "7.55",
            "effects": [
                effect for effect in bundled["effects"] if effect["action"] != "Devilment"
            ],
        }),
        encoding="utf-8",
    )
    assert _load_raid_effects(actions) == bundled["effects"]


def test_current_guide_patch_reuses_earlier_raid_effect_snapshot(tmp_path: Path) -> None:
    actions = tmp_path / "actions.json"
    actions.write_text('{"patch": "7.56"}')
    expected = resolve_effects(json.loads(Path("data/raid_effects/7.4.json").read_text()),
                               Path("data"), "7.56")
    assert _load_raid_effects(actions) == expected


def test_raid_effect_fallback_does_not_cross_expansions(tmp_path: Path) -> None:
    from ffxiv_potency.analysis import AnalysisError

    actions = tmp_path / "actions.json"
    actions.write_text('{"patch": "8.0"}')
    with pytest.raises(AnalysisError, match="raid-effect data.*missing"):
        _load_raid_effects(actions)
