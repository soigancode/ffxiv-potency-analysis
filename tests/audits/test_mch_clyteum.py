"""A 7.5 Clyteum run with two physical ranged DPS."""

import json
from pathlib import Path

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _format_fight
from ffxiv_potency.fflogs.partitions import require_current_patch


def test_clyteum_real_log_has_three_party_roles(tmp_path: Path, extract_fight) -> None:
    extract_fight(
        "mch_endgame_dungeons_7_4_7_5.zip", "Mbp7QCT439Y2gtZr/fight-1/source-2/",
    )
    fight = json.loads((tmp_path / "fight.json").read_text(encoding="utf-8"))
    rankings = json.loads((tmp_path / "rankings.json").read_text(encoding="utf-8"))
    assert (fight["encounterID"], rankings["rankings"]["data"][0]["partition"]) == (4551, 1)
    assert rankings["rankings"]["data"][0]["bracketData"] == 7.5
    assert rankings["rdps"]["data"][0]["roles"]["dps"]["characters"] == []
    require_current_patch(fight, rankings)
    result = analyze_saved_fight(tmp_path, Path("data/jobs/mch/7.4/actions.json"))
    assert result.fight_name == "the Clyteum"
    assert _format_fight(result) == "The Clyteum (clyteum)"
    assert result.party_bonus_percent == 3  # Tank, healer, and physical ranged DPS.
    assert result.unmatched == ()
