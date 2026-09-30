"""A ghosted Air Anchor grants Battery before its target is defeated."""

from pathlib import Path

from ffxiv_potency.analysis import analyze_saved_fight


def test_mch_clyteum_ghosted_air_anchor_grants_battery(
    tmp_path: Path, mch_actions: Path, extract_fight,
) -> None:
    extract_fight("mch_clyteum_battery_ghosts.zip", "6TAvFD89Mq2bCxK4/fight-1/source-2/")
    result = analyze_saved_fight(tmp_path, mch_actions)
    assert [q.gauge_spent for q in result.pet_deployments] == [
        80, 80, 60, 60, 60, 50, 60, 60, 80, 80, 100, 80, 90, 60, 60, 70,
    ]
    # Queen eight needs the missing 20 from Air Anchor at 5:50.421. Its
    # Visitant Trapper target was killed 357ms after calculation, before impact.
    assert ("Air Anchor", 1) in result.ghosted
    anchor = next(a for a in result.actions if a.name == "Air Anchor")
    assert anchor.uses == anchor.hits
