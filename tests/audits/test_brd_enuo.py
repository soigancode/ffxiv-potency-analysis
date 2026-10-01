"""Enuo BRD log in the global 7.5 partition."""

import json
from pathlib import Path
from zipfile import ZipFile

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.fflogs.partitions import require_current_patch


def test_brd_enuo_real_log_has_five_party_roles_and_no_unmatched_hits(
    tmp_path: Path, extract_fight,
) -> None:
    archive_name = "brd_enuo_sample.zip"
    prefix = "3JytA8XGhZamPxDL/fight-23/source-84/"
    extract_fight(archive_name, prefix)
    with ZipFile(Path(__file__).parents[1] / "fixtures/logs" / archive_name) as archive:
        (tmp_path / "combatant-info-events.json").write_bytes(
            archive.read(prefix + "combatant-info-events.json")
        )
    fight = json.loads((tmp_path / "fight.json").read_text(encoding="utf-8"))
    rankings = json.loads((tmp_path / "rankings.json").read_text(encoding="utf-8"))
    assert (fight["encounterID"], rankings["rankings"]["data"][0]["partition"]) == (1084, 7)
    require_current_patch(fight, rankings)

    result = analyze_saved_fight(tmp_path, Path("data/jobs/brd/7.4/actions.json"))
    assert result.party_bonus_percent == 5
    assert result.echo_status == "absent"
    assert result.food is not None
    assert result.food_missing_windows == ()
    assert result.unmatched == ()
    assert not any(penalty.name == "Damage Down" for penalty in result.damage_penalties)
