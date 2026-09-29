"""Saved full guide HTML is parsed and exported as normalized job data."""

import json
from datetime import UTC, datetime
from pathlib import Path

from ffxiv_potency.jobguide import import_saved_guide

FIXTURES = Path(__file__).parents[1] / "fixtures/jobguide"
SOURCE_URL = "https://eu.finalfantasyxiv.com/jobguide/machinist/"


def test_saved_full_guide_is_exported_as_json(tmp_path: Path) -> None:
    source = FIXTURES / "mch_full_7_5.html"
    destination = tmp_path / "machinist.json"

    assert (
        import_saved_guide(
            source,
            destination,
            job="machinist",
            patch="7.5",
            source_url=SOURCE_URL,
            retrieved_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
        )
        == destination
    )

    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["schema_version"] == 3
    assert document["job"] == "machinist"
    assert document["patch"] == "7.5"
    assert document["source"]["url"] == SOURCE_URL
    assert document["source"]["retrieved_at"] == "2026-09-23T12:00:00Z"
    assert len(document["actions"]) == 40
    assert next(trait for trait in document["traits"] if trait["name"] == "Increased Action Damage II")[
        "action_damage_multiplier"
    ] == 1.2

    actions = {action["name"]: action for action in document["actions"]}
    assert actions["Heated Slug Shot"]["potency"]["combo"] == {
        "potency": 320,
        "previous_actions": ["Heated Split Shot"],
    }
    assert actions["Reassemble"]["potency"] is None
    assert actions["Chain Saw"]["potency"]["falloff"] == {
        "additional_target_multiplier": 0.75,
    }
    assert actions["Bioblaster"]["potency"]["damage_over_time"] == {
        "potency_per_tick": 50,
        "duration_seconds": 15,
    }
