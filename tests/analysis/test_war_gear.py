"""Verify the user's 2.50 WAR sets and tank-specific potion/auto conversion."""

from pathlib import Path

import pytest

from ffxiv_potency.analysis.profiles import _load_combat_profile


@pytest.mark.parametrize("filename", ["7.4_savage.json", "7.55_relic.json"])
def test_warrior_tank_combat_factors(filename):
    path = Path("data/jobs/war/gear_sets") / filename
    profile = _load_combat_profile("warrior", gear_path=path)
    assert profile.player_damage_coefficient == 190
    assert profile.party_main_stat == 6795
    assert profile.potted_main_stat == 7336
    assert profile.player_potion_multiplier == pytest.approx(3077 / 2844)
    assert profile.action_trait_multiplier == 1
    assert profile.weapon_attribute_modifier == 105
    assert profile.auto_base_potency == 90
    assert profile.potion_action_names == ("Grade 4 Gemdraught of Strength [HQ]",)
