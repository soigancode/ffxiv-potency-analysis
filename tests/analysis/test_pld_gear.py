"""Shield-inclusive planner references and unambiguous automatic gear selection."""

import copy
import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis.profiles import _load_combat_profile
from ffxiv_potency.datasets import load_manifest, resolve_datasets, validate_manifest


@pytest.mark.parametrize("filename,sword,shield,dh,det,ten", [
    ("7.4_savage.json", 49658, 49679, 1230, 3066, 622),
    ("7.55_relic.json", 51000, 51021, 1230, 3146, 676),
    ("7.55_real.json", 52299, 51021, 1392, 3050, 600),
])
def test_planner_totals_and_combat_conversion(filename, sword, shield, dh, det, ten):
    path = Path("data/jobs/pld/gear_sets") / filename
    gear = json.loads(path.read_text())
    export = json.loads(Path("tests/fixtures/gear/pld_bis_xaela.json").read_text())
    row = next(s for s in export["sets"] if s["name"] == gear["source"]["set"])
    stats = row["computedStats"]
    assert row["items"]["Weapon"]["id"] == sword
    assert row["items"]["OffHand"]["id"] == shield
    assert (stats["dhit"], stats["determination"], stats["tenacity"]) == (dh, det, ten)
    assert (stats["strength"], stats["wdPhys"], stats["weaponDelay"]) == (6450, 158, 2.24)
    assert gear["solo_strength"] == stats["strength"]
    assert gear["party_strength"] == 6772
    assert row["effectiveFoodBonuses"] == {"crit": 91, "determination": 151}
    for key, planner in [("critical_hit", "crit"), ("direct_hit", "dhit"),
                         ("determination", "determination"), ("tenacity", "tenacity")]:
        assert gear[key] == stats[planner]
    p = _load_combat_profile("paladin", gear_path=path)
    assert (p.weapon_attribute_modifier, p.player_damage_coefficient, p.action_trait_multiplier) == (100, 190, 1)
    assert (p.party_main_stat, p.potted_main_stat) == (6772, 7313)
    assert p.player_potion_multiplier == pytest.approx(3067 / 2834)
    assert 90 * int((440 * 100 // 1000 + 158) * 2.24 / 3) / 202 == pytest.approx(66.8316831683)


def test_automatic_gear_and_selectable_overrides():
    assert resolve_datasets("pld", {"playedPatch": "7.5"}).gear_id == "savage_7_4"
    assert resolve_datasets("pld", {"playedPatch": "7.55"}).gear_id == "real_7_55"
    assert resolve_datasets("pld", {"playedPatch": "7.56"}).gear_id == "real_7_55"
    for selected in ("relic_7_55", "savage_7_4", "real_7_55"):
        result = resolve_datasets("pld", {"playedPatch": "7.56"}, gear=selected)
        assert (result.gear_id, result.gear_source) == (selected, "user-selected")
    document, root = load_manifest("pld")
    assert len(document["gear_sets"]) == 3
    broken = copy.deepcopy(document)
    broken["gear_sets"][1]["automatic"] = True
    with pytest.raises(ValueError, match="overlapping"):
        validate_manifest(broken, root)
