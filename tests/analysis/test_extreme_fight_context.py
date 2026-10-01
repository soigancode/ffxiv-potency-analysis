"""Extreme eligibility checks using a synthetic context around saved BRD events."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.analysis.errors import AnalysisError
from ffxiv_potency.fflogs.partitions import require_current_patch

ACTIONS = Path(__file__).parents[2] / "data/jobs/brd/7.4/actions.json"


@pytest.fixture
def extreme_context(tmp_path: Path, extract_fight) -> Path:
    # These are real BRD damage events, but the encounter context is synthetic;
    # this checks gating, not Doomtrain mechanics or potency totals.
    extract_fight("brd_vamp_fatale.zip", "Kn9vkBgZT3RPGxDf/fight-21/source-4/")
    fight_path = tmp_path / "fight.json"
    fight = json.loads(fight_path.read_text(encoding="utf-8"))
    fight.update({"encounterID": 1083,
                  "reportStartTime": datetime(2026, 2, 1, tzinfo=UTC).timestamp() * 1000})
    fight_path.write_text(json.dumps(fight), encoding="utf-8")
    (tmp_path / "rankings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "combatant-info-events.json").write_text(
        json.dumps([{"sourceID": 4, "auras": []}]), encoding="utf-8",
    )
    return tmp_path


def test_unranked_extreme_with_verified_absent_echo_can_be_analysed(
    extreme_context: Path,
) -> None:
    fight = json.loads((extreme_context / "fight.json").read_text(encoding="utf-8"))
    require_current_patch(fight, {})
    result = analyze_saved_fight(extreme_context, ACTIONS)
    assert result.encounter_id == 1083
    assert result.echo_status == "absent"
    assert result.rdps is None and result.ndps is None


@pytest.mark.parametrize("auras,reason", [
    ([{"ability": 1000042}], "Echo is not supported"),
    (None, "initial auras are missing"),
])
def test_extreme_requires_verified_absence_of_echo(
    extreme_context: Path, auras: list[dict[str, int]] | None, reason: str,
) -> None:
    combatants = [{"sourceID": 4, "auras": auras}] if auras is not None else []
    (extreme_context / "combatant-info-events.json").write_text(
        json.dumps(combatants), encoding="utf-8",
    )
    with pytest.raises(AnalysisError, match=reason):
        analyze_saved_fight(extreme_context, ACTIONS)


def test_extreme_does_not_guess_damage_down_strength(extreme_context: Path) -> None:
    path = extreme_context / "damage-events.json"
    events = json.loads(path.read_text(encoding="utf-8"))
    hit = next(event for event in events
               if event.get("type") == "damage" and event.get("sourceID") == 4
               and event.get("amount", 0) > 0)
    hit["buffs"] = "1002911."
    path.write_text(json.dumps(events), encoding="utf-8")
    with pytest.raises(AnalysisError, match="Damage Down potency is not configured"):
        analyze_saved_fight(extreme_context, ACTIONS)
