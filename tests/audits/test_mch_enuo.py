"""Enuo MCH log in the global 7.5 partition."""

from pathlib import Path
from zipfile import ZipFile

from ffxiv_potency.analysis import analyze_saved_fight


def test_enuo_real_log_has_landed_damage_without_damage_down(
    tmp_path: Path, extract_fight,
) -> None:
    extract_fight("mch_enuo_sample.zip", "VaPWAkyRCTDZ1KFB/fight-5/source-45/")
    with ZipFile(Path(__file__).parents[1] / "fixtures/logs/mch_enuo_sample.zip") as archive:
        (tmp_path / "combatant-info-events.json").write_bytes(archive.read(
            "VaPWAkyRCTDZ1KFB/fight-5/source-45/combatant-info-events.json"
        ))
    result = analyze_saved_fight(tmp_path, Path("data/machinist/7.55/actions.json"))
    assert result.encounter_id == 1084
    assert result.echo_status == "absent"
    assert result.unmatched == ()
    assert not any(penalty.name == "Damage Down" for penalty in result.damage_penalties)
