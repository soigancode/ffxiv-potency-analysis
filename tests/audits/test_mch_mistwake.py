"""A 7.4 Mistwake run with two physical ranged DPS."""

import json
from dataclasses import replace
from pathlib import Path

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _format_fight
from ffxiv_potency.fflogs.partitions import require_current_patch


def test_mistwake_real_log_has_three_party_roles(tmp_path: Path, extract_fight) -> None:
    extract_fight(
        "mch_endgame_dungeons_7_4_7_5.zip", "JyjKZrpP91QM7F4Y/fight-1/source-2/",
    )
    fight = json.loads((tmp_path / "fight.json").read_text(encoding="utf-8"))
    rankings = json.loads((tmp_path / "rankings.json").read_text(encoding="utf-8"))
    assert (fight["encounterID"], rankings["rankings"]["data"][0]["partition"]) == (4549, 1)
    assert rankings["rankings"]["data"][0]["bracketData"] == 7.4
    assert rankings["rdps"]["data"][0]["roles"]["dps"]["characters"] == []
    require_current_patch(fight, rankings)
    result = analyze_saved_fight(tmp_path, Path("data/machinist/7.55/actions.json"))
    assert result.party_bonus_percent == 3  # Tank, healer, and physical ranged DPS.
    assert result.unmatched == ()
    assert _format_fight(result) == "Mistwake (4549)"
    assert _format_fight(replace(
        result, fight_name="Treno Catoblepas / Thundergust Griffin / Amdusias",
    )) == "Mistwake (4549)"
