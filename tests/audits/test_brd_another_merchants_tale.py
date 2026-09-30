"""Two BRD AMT kills audit Damage Down and varying report fight names."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.cli import _format_fight
from ffxiv_potency.fflogs.partitions import require_current_patch

ARCHIVE = "brd_another_merchants_tale_damage_down.zip"
ACTIONS = Path(__file__).parents[2] / "data/bard/7.55/actions.json"


@pytest.mark.parametrize("prefix,window_count,affected_hits,first,final", [
    ("a-GKn4NPzYZtJdfcXM/fight-22/source-94/", 2, 90, 167.763, 780.071),
    ("Mza8wxKTYLWJrP2n/fight-9/source-80/", 1, 53, 457.53, 487.527),
])
def test_merchant_tale_damage_down_and_fight_identity(
    tmp_path: Path, extract_fight, prefix: str, window_count: int,
    affected_hits: int, first: float, final: float,
) -> None:
    extract_fight(ARCHIVE, prefix)
    fight = json.loads((tmp_path / "fight.json").read_text(encoding="utf-8"))
    rankings = json.loads((tmp_path / "rankings.json").read_text(encoding="utf-8"))
    require_current_patch(fight, rankings)
    assert fight["encounterID"] == 4550
    assert rankings["rankings"]["data"][0]["partition"] == 1
    result = analyze_saved_fight(tmp_path, ACTIONS)
    assert _format_fight(result) == "Another Merchant's Tale (4550)"
    assert result.unmatched == ()
    assert result.party_bonus_percent == 4
    penalty, = result.damage_penalties
    assert penalty.name == "Damage Down"
    assert penalty.multiplier == 0.85
    assert penalty.affected_hits == affected_hits
    windows = [window for window in result.status_windows if window.name == "Damage Down"]
    assert len(windows) == window_count
    assert windows[0].start_seconds == pytest.approx(first)
    assert windows[-1].end_seconds == pytest.approx(final)
    assert all(window.end_reason == "expired" for window in windows)

    # The same song status has a 1.01 recorded multiplier without Damage Down
    # and a rounded 0.86 with it: 1.01 * 0.85 = 0.8585.
    events = json.loads((tmp_path / "damage-events.json").read_text(encoding="utf-8"))
    source = int(prefix.split("source-")[1].split("/")[0])
    observed = {
        (event.get("buffs"), event.get("multiplier"))
        for event in events
        if event.get("sourceID") == source and event.get("abilityGameID") == 16495
        and event.get("type") == "damage" and event.get("amount", 0) > 0
    }
    assert ("1002217.", 1.01) in observed
    assert ("1002911.1002217.", 0.86) in observed
