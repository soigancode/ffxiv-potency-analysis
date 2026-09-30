"""Queen Battery audited independently against damage from uncontested Queens."""

import json
from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze_saved_fight

_AUDIT = json.loads(
    (Path(__file__).parents[1] / "fixtures/audits/mch_dancing_mad_battery_audit.json")
    .read_text()
)


@pytest.mark.parametrize("case", _AUDIT["cases"], ids=lambda case: case["report"])
def test_mch_dancing_mad_ghosted_battery_matches_queen_damage(
    case, tmp_path: Path, mch_actions: Path, extract_fight,
) -> None:
    extract_fight(
        "mch_dancing_mad_battery_ghosts.zip",
        f"{case['report']}/fight-{case['fight']}/source-{case['source']}/",
    )
    result = analyze_saved_fight(tmp_path, mch_actions)
    assert [q.gauge_spent for q in result.pet_deployments] == case["gauges"]
    assert not any(q.gauge_assumed for q in result.pet_deployments)

    # Independent recorded-damage constraints. The baseline intervals come
    # from other Queens with known Battery, not the analyser's potency totals.
    base = {"Arm Punch": 120, "Roller Dash": 240,
            "Pile Bunker": 340, "Crowned Collider": 390}
    for check in case["damage_checks"]:
        gauge = result.pet_deployments[check["queen"] - 1].gauge_spent
        bounds = {key: reference["interval"]
                  for key, reference in check["reference_intervals"].items()}
        for hit in check["hits"]:
            key = str((hit["potted"], hit["action"]))
            potency = base[hit["action"]] * gauge / 50
            dh = 1.25 if hit["dh"] else 1
            lower = (hit["amount"] - 2) / (
                potency * dh * (hit["multiplier"] + .005) * 1.05
            )
            upper = (hit["amount"] + 2) / (
                potency * dh * (hit["multiplier"] - .005) * .95
            )
            bounds[key] = [max(bounds[key][0], lower), min(bounds[key][1], upper)]
        assert all(lower <= upper for lower, upper in bounds.values())

    # Every resource ghost retains zero landed action potency: action hits and
    # totals come only from landed packets, not the added calculated records.
    events = json.loads((tmp_path / "damage-events.json").read_text())
    ghost_packets = {g["packet"] for g in case["ghosts"]}
    assert not any(e.get("type") == "damage" and e.get("amount", 0) > 0
                   and e.get("packetID") in ghost_packets for e in events)
    assert sum(count for _, count in result.ghosted) >= len(ghost_packets)
