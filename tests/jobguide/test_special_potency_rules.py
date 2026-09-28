from pathlib import Path

from ffxiv_potency.jobguide import Action, Potency, inspect_job_actions

FIXTURES = Path(__file__).parents[1] / "fixtures/jobguide"


def load_actions() -> dict[str, Action]:
    html = (FIXTURES / "machinist_full_7_5.html").read_text(encoding="utf-8")
    report = inspect_job_actions(html)
    return {action.name: action for action in report.actions}


def as_dict(potency: Potency | None) -> dict[str, object] | None:
    if potency is None:
        return None
    return potency.to_dict()


def test_remaining_special_potency_rules() -> None:
    actions = load_actions()

    assert [gain.to_dict() for gain in actions["Air Anchor"].gauge_gains] == [
        {"gauge": "Battery Gauge", "amount": 20, "requires_combo": False}
    ]
    assert [gain.to_dict() for gain in actions["Heated Clean Shot"].gauge_gains] == [
        {"gauge": "Heat Gauge", "amount": 5, "requires_combo": True},
        {"gauge": "Battery Gauge", "amount": 10, "requires_combo": True},
    ]

    assert as_dict(actions["Hypercharge"].potency) == {
        "modifier": {
            "bonus": 20,
            "applies_to": "single-target weaponskills",
            "maximum_uses": 5,
        }
    }
    assert actions["Rook Autoturret"].potency is None
    assert actions["Rook Autoturret"].deploys_actor == "Rook Autoturret"
    assert as_dict(actions["Volley Fire"].potency) == {
        "base": 35,
        "gauge_scaling": {
            "gauge": "Battery Gauge",
            "maximum_potency": 70,
            "minimum_cost": 50,
        },
    }
    assert actions["Volley Fire"].source_actor == "Rook Autoturret"
    assert actions["Volley Fire"].derived_from == "Rook Autoturret"
    assert actions["Rook Overdrive"].potency is None
    assert actions["Rook Overdrive"].triggers_action == "Rook Overload"
    assert as_dict(actions["Rook Overload"].potency) == {
        "base": 160,
        "gauge_scaling": {"gauge": "Battery Gauge", "maximum_potency": 320},
    }
    assert as_dict(actions["Wildfire"].potency) == {
        "triggered": {"potency_per_trigger": 240, "maximum_triggers": 6}
    }
    assert as_dict(actions["Ricochet"].potency) == {
        "base": 130,
        "falloff": {"additional_target_multiplier": 0.7},
    }
    assert as_dict(actions["Flamethrower"].potency) == {
        "damage_over_time": {"potency_per_tick": 120, "duration_seconds": 10}
    }
    assert actions["Automaton Queen"].potency is None
    assert actions["Automaton Queen"].deploys_actor == "Automaton Queen"
    assert actions["Queen Overdrive"].potency is None
    assert actions["Queen Overdrive"].triggers_action == "Pile Bunker"
    assert as_dict(actions["Pile Bunker"].potency) == {
        "base": 340,
        "gauge_scaling": {"gauge": "Battery Gauge", "maximum_potency": 680},
    }
    assert as_dict(actions["Roller Dash"].potency) == {
        "base": 240,
        "gauge_scaling": {"gauge": "Battery Gauge", "maximum_potency": 480},
    }
    for name in ("Arm Punch", "Roller Dash", "Pile Bunker", "Crowned Collider"):
        assert actions[name].source_actor == "Automaton Queen"
