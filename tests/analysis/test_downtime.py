"""Missing hits during recorded downtime remain separate from confirmed ghosts."""

import json
from pathlib import Path

import pytest

from ffxiv_potency import cli
from ffxiv_potency.analysis import analyze_saved_fight
from ffxiv_potency.reporting import confirmed_ghosts, issue_notes

JOBS = [("pld", "Paladin", "Holy Circle"), ("war", "Warrior", "Overpower"),
        ("brd", "Bard", "Burst Shot"), ("mch", "Machinist", "Spread Shot"),
        ("dnc", "Dancer", "Windmill")]


def analyze_missing_hit(tmp_path, job, subtype, action, *, cast_time=3000, target=-1,
                        updates=True, other_target=False):
    events = [{"type": "targetabilityupdate", "timestamp": 2000,
               "sourceID": 2, "targetable": 0},
              {"type": "targetabilityupdate", "timestamp": 5000,
               "sourceID": 2, "targetable": 1}]
    if other_target:
        events.append({"type": "targetabilityupdate", "timestamp": 0,
                       "sourceID": 3, "targetable": 1})
    hit = {"type": "damage", "timestamp": 1000, "sourceID": 1,
           "targetID": 2, "abilityGameID": 1, "packetID": 10, "amount": 1000, "hitType": 1}
    data = {
        "fight": {"startTime": 0, "endTime": 10000, "friendlyPlayers": [1]},
        "master-data": {
            "actors": [{"id": 1, "type": "Player", "name": "Player", "subType": subtype},
                       {"id": 2, "type": "NPC", "name": "Boss", "subType": "Boss"},
                       {"id": 3, "type": "NPC", "name": "Add"},
                       {"id": -1, "name": "Environment"}],
            "abilities": [{"gameID": 1, "name": action}],
        },
        "damage-events": [hit],
        "cast-events": [{**hit, "type": "cast"},
                        {"type": "cast", "timestamp": cast_time, "sourceID": 1,
                         "targetID": target, "abilityGameID": 1, "packetID": 20}],
        "targetability-events": events if updates else [],
    }
    for name, value in data.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    return analyze_saved_fight(tmp_path, Path(f"data/jobs/{job}/7.4/actions.json"),
                               use_cache=False)


@pytest.mark.parametrize("job,subtype,action", JOBS)
@pytest.mark.parametrize("target", [-1, 2])
def test_all_jobs_label_recorded_downtime_without_confirming_a_ghost(
    tmp_path, capsys, job, subtype, action, target,
):
    result = analyze_missing_hit(tmp_path, job, subtype, action, target=target)
    assert result.ghosted_ending_times == ((action, ((3.0, "downtime"),)),)
    assert confirmed_ghosts(result) == []
    assert "G" not in issue_notes(result)
    cli._print_analysis(result)
    output = capsys.readouterr().out
    assert f"00m03s {action} on {'Environment' if target == -1 else 'Boss'} (downtime)" in output
    assert "Confirmed ghosted hits: 0" in output


@pytest.mark.parametrize("updates,other_target", [(False, False), (True, True)])
def test_downtime_requires_evidence_and_no_available_other_target(tmp_path, updates, other_target):
    result = analyze_missing_hit(tmp_path, *JOBS[0], updates=updates, other_target=other_target)
    assert result.ghosted_ending_times == ()


def test_cast_before_disappearance_retains_confirmed_ghost_reason(tmp_path):
    result = analyze_missing_hit(tmp_path, *JOBS[0], cast_time=1900, target=2)
    assert confirmed_ghosts(result) == [
        (1.9, "Holy Circle", "Boss", "target became untargetable before hit landed"),
    ]
