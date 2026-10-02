"""Audit Dancer AoE damage and proc histories across complete Mistwake runs."""

import json
from collections import Counter

import pytest

CASES = [
    (
        "NxWyGfDp9grtkKFw/fight-1/source-4",
        ("Largeus Donjus", "savage_7_4", 727, 205, 1, 33, 55, 29, 29, 13),
        3,
        (40, 36, 28),
        47.37039349439945,
    ),
    (
        "x1Q8YXTHyPJkFrhV/fight-1/source-3",
        ("Aine Nahath", "savage_7_4", 828, 219, 3, 33, 53, 27, 27, 13),
        4,
        (44, 39, 27),
        47.38388115490463,
    ),
    (
        "PJVg9pBRXFGxbYw2/fight-5/source-2",
        ("Buckfast Abbey", "savage_7_4", 875, 221, 3, 34, 67, 41, 41, 22),
        4,
        (50, 41, 41),
        54.148494632731214,
    ),
]


@pytest.mark.parametrize("prefix,expected,party_bonus,trials,score", CASES)
def test_dancer_full_dungeon_run(tmp_path, audit_dnc, prefix, expected, party_bonus, trials, score):
    result = audit_dnc(tmp_path, "dnc_mistwake.zip", prefix, expected, (0,))
    assert result.encounter_id == 4549
    assert result.party_bonus_percent == party_bonus
    proc = result.dnc_procs
    assert proc is not None
    assert proc.starting_feathers_source == "fresh dungeon or Criterion run"
    assert tuple(sum(count for _, count in stage.trials) for stage in proc.ready_procs) == trials
    assert proc.fan_trials == trials[2]
    assert proc.combined_feather_luck_min == pytest.approx(score)

    # These logs exercise both AoE unlocks and AoE Feather generation/spending.
    # Count landed targets separately to establish that packets really are AoE.
    master = json.loads((tmp_path / "master-data.json").read_text())
    names = {action["gameID"]: action["name"] for action in master["abilities"]}
    damage = json.loads((tmp_path / "damage-events.json").read_text())
    hits = Counter(
        (names[event["abilityGameID"]], event["packetID"])
        for event in damage
        if event["type"] == "damage" and event.get("amount", 0) > 0
    )
    for name in ("Windmill", "Bladeshower", "Rising Windmill", "Bloodshower", "Fan Dance II"):
        assert any(action == name and targets > 1 for (action, _), targets in hits.items()), name
