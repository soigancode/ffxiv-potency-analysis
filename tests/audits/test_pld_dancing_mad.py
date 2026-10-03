"""Independently audit supplied PLD dancing_mad logs."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.reporting import confirmed_ghosts

from .pld_audit import audit_pld

CASES = ['2NMD8tkyVC3XcFxY/fight-9/source-7', 'dzyx6FtjcQXMDJP3/fight-13/source-98', 'kp4CzadVbJXQ216Z/fight-7/source-23']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_dancing_mad.zip", prefix)
    result = analyze_saved_fight(tmp_path, Path("data/jobs/pld/7.4/actions.json"), use_cache=False)
    assert result.pld is not None
    assert not any(target in {"Chaos", "Exdeath"} for _, _, target, _ in confirmed_ghosts(result))
    if prefix.startswith("dzyx6FtjcQXMDJP3"):
        burst = next(b for b in result.pld.bursts if b.seconds == 429.496)
        assert burst.follow_ups[3].casts == 1
        # Two landed targets: unenhanced Valor 500 * (1 + 0.4).
        assert burst.follow_ups[3].potency == 700
        assert "Blade of Valor: unenhanced" in burst.notes
        # Compare the delayed packet with a later enhanced Valor on the same
        # target, independently of the analyzer's selected spell potency.
        damage = json.loads((tmp_path / "damage-events.json").read_text())
        hits = [e for e in damage if e.get("type") == "damage"
                and e.get("abilityGameID") == 25750]
        primary = next(e for e in hits if e.get("packetID") == 16176 and e["targetID"] == 17)
        secondary = next(e for e in hits if e.get("packetID") == 16176 and e["targetID"] == 18)
        enhanced = next(e for e in hits if e.get("packetID") == 17051 and e["targetID"] == 17)
        for hit in (primary, secondary, enhanced):
            assert hit["hitType"] == 1
            assert not hit.get("overkill")
            assert "1000049" not in hit.get("buffs", "").split(".")
        assert not primary.get("directHit") and not enhanced.get("directHit")
        assert secondary.get("directHit")
        # Both damage rolls range from 95% to 105%. Base Valor is half the
        # enhanced potency; the second target takes 40% with a 1.25 DH bonus.
        normalized = primary["amount"] / primary["multiplier"]
        reference = enhanced["amount"] / enhanced["multiplier"]
        assert 0.5 * 0.95 / 1.05 <= normalized / reference <= 0.5 * 1.05 / 0.95
        falloff = secondary["amount"] / secondary["multiplier"] / 1.25 / normalized
        assert 0.4 * 0.95 / 1.05 <= falloff <= 0.4 * 1.05 / 0.95


@pytest.mark.parametrize('action', ['Riot Blade', 'Royal Authority'])
def test_removed_combo_field_recovers_recorded_potency(tmp_path, action):
    import json
    from pathlib import Path
    from zipfile import ZipFile

    from ffxiv_potency.analysis import analyze_saved_fight

    prefix = 'dzyx6FtjcQXMDJP3/fight-13/source-98'
    with ZipFile('tests/fixtures/logs/pld_dancing_mad.zip') as z:
        for member in z.namelist():
            if member.startswith(prefix + '/') and member.endswith('.json'):
                (tmp_path / Path(member).name).write_bytes(z.read(member))
    actions_path = Path('data/jobs/pld/7.4/actions.json')
    before = analyze_saved_fight(tmp_path, actions_path, use_cache=False)
    names = {a['gameID']: a['name'] for a in json.loads(
        (tmp_path / 'master-data.json').read_text())['abilities']}
    path = tmp_path / 'damage-events.json'
    damage = json.loads(path.read_text())
    hit = next(e for e in damage if e.get('type') == 'damage'
               and names.get(e.get('abilityGameID')) == action and e.get('bonusPercent', 0) > 0
               and not e.get('overkill'))
    del hit['bonusPercent']
    path.write_text(json.dumps(damage))
    after = analyze_saved_fight(tmp_path, actions_path, use_cache=False)
    assert after.pld is not None and after.pld.combos is not None
    assert after.pld.combos.inferred[0].comboed
    assert after.actions == before.actions
    assert after.potency_min == after.potency_max == before.potency_min
    assert after.pps_min == before.pps_min
    assert after.potion == before.potion
    assert after.luck_score == before.luck_score
