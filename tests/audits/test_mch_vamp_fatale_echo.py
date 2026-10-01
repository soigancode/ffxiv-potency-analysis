"""Echo partition audit from the saved M9S rank-one report and API probe."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.errors import AnalysisError
from ffxiv_potency.analysis.party import party_bonus_percent
from ffxiv_potency.fflogs.partitions import require_current_patch


def test_mch_vamp_fatale_echo_is_an_initial_aura_not_a_damage_buff(
    extract_fight, tmp_path: Path,
) -> None:
    extract_fight("mch_vamp_fatale_echo.zip", "CcvRV1j2mYyD8FkG/fight-4/source-287/")
    probe = json.loads((Path(__file__).parents[1] / "fixtures/audits"
                        / "mch_m9s_partition_probe.json").read_text(encoding="utf-8"))
    echo = next(row for row in probe["partitions"] if row["partition"] == 13)
    assert echo["report"] == "CcvRV1j2mYyD8FkG"
    assert echo["report_partitions"] == [13]
    assert len(echo["initial_echo_player_ids"]) == 8
    assert 287 in echo["initial_echo_player_ids"]

    fight = json.loads((tmp_path / "fight.json").read_text(encoding="utf-8"))
    rankings = json.loads((tmp_path / "rankings.json").read_text(encoding="utf-8"))
    require_current_patch(fight, rankings)
    hits = json.loads((tmp_path / "damage-events.json").read_text(encoding="utf-8"))
    player_hits = [hit for hit in hits if hit.get("type") == "damage"
                   and hit.get("sourceID") == 287 and hit.get("amount", 0) > 0]
    assert player_hits
    assert all("1000042" not in hit.get("buffs", "").split(".") for hit in player_hits)
    assert player_hits[0]["multiplier"] == pytest.approx(1.05)  # potion, not 1.12 Echo

    actions = Path(__file__).parents[2] / "data/jobs/mch/7.4/actions.json"
    with pytest.raises(AnalysisError, match="initial Echo aura"):
        analyze_saved_fight(tmp_path, actions)
    # The earlier API probe recorded these eight initial auras, but the old
    # downloaded ZIP predates combatant-info-events.json. Reconstruct only that
    # field from the independent probe, leaving the damage archive untouched.
    combatants = [{"sourceID": actor_id, "auras": [{"ability": 1000042}]}
                  for actor_id in echo["initial_echo_player_ids"]]
    (tmp_path / "combatant-info-events.json").write_text(
        json.dumps([{"sourceID": 287, "auras": []}]), encoding="utf-8",
    )
    with pytest.raises(AnalysisError, match="initial Echo aura"):
        analyze_saved_fight(tmp_path, actions)
    (tmp_path / "combatant-info-events.json").write_text(
        json.dumps(combatants), encoding="utf-8",
    )
    with_aura = analyze_saved_fight(tmp_path, actions)
    assert with_aura.echo_status == "observed"
    assert with_aura.reduced_damage_hits[0].damage == pytest.approx(20114 / 1.12)
    assert with_aura.reduced_damage_hits[0].overkill == pytest.approx(10615 / 1.12)
    assert with_aura.ndps == pytest.approx(45864.747786158)
    # Normalization changes only the in-memory events, never the saved archive.
    assert json.loads((tmp_path / "damage-events.json").read_text(encoding="utf-8")) == hits

    master = json.loads((tmp_path / "master-data.json").read_text(encoding="utf-8"))
    limit_break = next(actor["id"] for actor in master["actors"]
                       if actor.get("subType") == "LimitBreak")
    fight["friendlyPlayers"] = [*echo["initial_echo_player_ids"], limit_break]
    assert party_bonus_percent(fight, master, 287) == 5
