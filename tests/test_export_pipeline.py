import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ffxiv_potency.jobguide import import_saved_guide

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_URL = "https://eu.finalfantasyxiv.com/jobguide/machinist/"


def test_saved_html_is_parsed_and_exported_as_json(tmp_path: Path) -> None:
    destination = tmp_path / "machinist.json"

    result = import_saved_guide(
        FIXTURES / "machinist_combo.html",
        destination,
        job="machinist",
        patch="7.5",
        source_url=SOURCE_URL,
        retrieved_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )

    assert result == destination
    assert destination.exists()
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document == {
        "schema_version": 1,
        "job": "machinist",
        "patch": "7.5",
        "source": {
            "url": SOURCE_URL,
            "retrieved_at": "2026-09-23T12:00:00Z",
        },
        "actions": [
            {
                "name": "Heated Split Shot",
                "level": 54,
                "type": "Weaponskill",
                "potency": {"base": 220},
                "description": [
                    "Delivers an attack with a potency of 220.",
                    "Additional Effect: Increases Heat Gauge by 5",
                ],
                "gauge_gains": [{"gauge": "Heat Gauge", "amount": 5, "requires_combo": False}],
            },
            {
                "name": "Heated Slug Shot",
                "level": 60,
                "type": "Weaponskill",
                "potency": {
                    "base": 140,
                    "combo": {
                        "potency": 320,
                        "previous_actions": ["Heated Split Shot"],
                    },
                },
                "description": [
                    "Delivers an attack with a potency of 140.",
                    "Combo Action: Heated Split Shot",
                    "Combo Potency: 320",
                    "Combo Bonus: Increases Heat Gauge by 5",
                ],
                "gauge_gains": [{"gauge": "Heat Gauge", "amount": 5, "requires_combo": True}],
            },
            {
                "name": "Reassemble",
                "level": 10,
                "type": "Ability",
                "potency": None,
                "description": [
                    "Guarantees that next weaponskill is a critical direct hit.",
                    "Duration: 5s",
                    "Maximum Charges: 2",
                ],
            },
        ],
    }


@pytest.mark.parametrize(
    ("fixture", "expected_potency"),
    [
        (
            "machinist_chain_saw.html",
            {
                "base": 660,
                "falloff": {"additional_target_multiplier": 0.75},
            },
        ),
        (
            "machinist_bioblaster.html",
            {
                "base": 50,
                "damage_over_time": {"potency_per_tick": 50, "duration_seconds": 15},
            },
        ),
    ],
    ids=["aoe-falloff", "damage-over-time"],
)
def test_special_potency_is_exported_as_json(
    tmp_path: Path, fixture: str, expected_potency: dict
) -> None:
    destination = tmp_path / "machinist.json"
    import_saved_guide(
        FIXTURES / fixture,
        destination,
        job="machinist",
        patch="7.5",
        source_url=SOURCE_URL,
        retrieved_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["actions"][0]["potency"] == expected_potency
