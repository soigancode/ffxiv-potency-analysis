"""Typed domain models for data extracted from the job guide."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Trait:
    """A PvE trait, with an interpreted multiplier when its effect is supported."""

    name: str
    level: int
    description: tuple[str, ...]
    action_damage_multiplier: float | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "level": self.level,
            "description": list(self.description),
        }
        if self.action_damage_multiplier is not None:
            result["action_damage_multiplier"] = self.action_damage_multiplier
        return result


@dataclass(frozen=True, slots=True)
class ComboPotency:
    """Potency applied when an action completes a valid combo."""

    potency: int
    previous_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.potency <= 0:
            raise ValueError("combo potency must be positive")
        if not self.previous_actions:
            raise ValueError("a combo must specify at least one previous action")

    def to_dict(self) -> dict[str, int | list[str]]:
        return {
            "potency": self.potency,
            "previous_actions": list(self.previous_actions),
        }


@dataclass(frozen=True, slots=True)
class AoeFalloff:
    """Damage multiplier applied to enemies after the primary target."""

    additional_target_multiplier: float

    def __post_init__(self) -> None:
        if not 0 < self.additional_target_multiplier <= 1:
            raise ValueError("additional-target multiplier must be greater than 0 and at most 1")

    def to_dict(self) -> dict[str, float]:
        return {"additional_target_multiplier": self.additional_target_multiplier}


@dataclass(frozen=True, slots=True)
class DamageOverTime:
    """A periodic damage effect applied by an action."""

    potency_per_tick: int
    duration_seconds: int

    def __post_init__(self) -> None:
        if self.potency_per_tick <= 0:
            raise ValueError("damage-over-time potency must be positive")
        if self.duration_seconds <= 0:
            raise ValueError("damage-over-time duration must be positive")

    def to_dict(self) -> dict[str, int]:
        return {
            "potency_per_tick": self.potency_per_tick,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class StackPotency:
    """Exact potency for each number of consumed stacks or coda."""

    resource: str
    values: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.resource or not self.values or any(value <= 0 for value in self.values):
            raise ValueError("stack potency needs a resource and positive values")

    def to_dict(self) -> dict[str, str | dict[str, int]]:
        return {
            "resource": self.resource,
            "by_count": {str(count): value for count, value in enumerate(self.values, 1)},
        }


@dataclass(frozen=True, slots=True)
class GaugeScaling:
    """Maximum potency reached by spending more of a named gauge."""

    gauge: str
    maximum_potency: int
    minimum_cost: int | None = None

    def __post_init__(self) -> None:
        if not self.gauge:
            raise ValueError("gauge must not be empty")
        if self.maximum_potency <= 0:
            raise ValueError("maximum gauge-scaled potency must be positive")
        if self.minimum_cost is not None and self.minimum_cost <= 0:
            raise ValueError("minimum gauge cost must be positive")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "gauge": self.gauge,
            "maximum_potency": self.maximum_potency,
        }
        if self.minimum_cost is not None:
            result["minimum_cost"] = self.minimum_cost
        return result


@dataclass(frozen=True, slots=True)
class TriggeredPotency:
    """Potency accumulated once for each qualifying trigger."""

    potency_per_trigger: int
    maximum_triggers: int

    def __post_init__(self) -> None:
        if self.potency_per_trigger <= 0 or self.maximum_triggers <= 0:
            raise ValueError("triggered potency values must be positive")

    def to_dict(self) -> dict[str, int]:
        return {
            "potency_per_trigger": self.potency_per_trigger,
            "maximum_triggers": self.maximum_triggers,
        }


@dataclass(frozen=True, slots=True)
class PotencyModifier:
    """A temporary flat potency increase applied to qualifying actions."""

    bonus: int
    applies_to: str
    maximum_uses: int

    def __post_init__(self) -> None:
        if self.bonus <= 0 or self.maximum_uses <= 0:
            raise ValueError("potency modifier values must be positive")
        if not self.applies_to:
            raise ValueError("modifier target must not be empty")

    def to_dict(self) -> dict[str, int | str]:
        return {
            "bonus": self.bonus,
            "applies_to": self.applies_to,
            "maximum_uses": self.maximum_uses,
        }


@dataclass(frozen=True, slots=True)
class ConditionalPotency:
    """An action's potency under a named condition from the job guide."""

    condition: str
    potency: int

    def __post_init__(self) -> None:
        if not self.condition or self.potency <= 0:
            raise ValueError("conditional potency needs a condition and positive potency")


@dataclass(frozen=True, slots=True)
class GaugeGain:
    """Gauge granted when an action lands, optionally only as a combo bonus."""

    gauge: str
    amount: int
    requires_combo: bool = False

    def __post_init__(self) -> None:
        if not self.gauge or self.amount <= 0:
            raise ValueError("gauge gain requires a name and positive amount")

    def to_dict(self) -> dict[str, int | str | bool]:
        return {
            "gauge": self.gauge,
            "amount": self.amount,
            "requires_combo": self.requires_combo,
        }


@dataclass(frozen=True, slots=True)
class Potency:
    """Normalized direct, periodic, triggered, or modifying potency rules."""

    base: int | None = None
    combo: ComboPotency | None = None
    falloff: AoeFalloff | None = None
    damage_over_time: DamageOverTime | None = None
    gauge_scaling: GaugeScaling | None = None
    triggered: TriggeredPotency | None = None
    modifier: PotencyModifier | None = None
    stack_potency: StackPotency | None = None
    conditional_potencies: tuple[ConditionalPotency, ...] = ()

    def __post_init__(self) -> None:
        if self.base is not None and self.base <= 0:
            raise ValueError("base potency must be positive")
        conditions = [entry.condition for entry in self.conditional_potencies]
        if len(conditions) != len(set(conditions)):
            raise ValueError("conditional potency conditions must be unique")
        if not any(
            (self.base, self.damage_over_time, self.triggered, self.modifier, self.stack_potency)
        ):
            raise ValueError("at least one potency rule is required")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.base is not None:
            result["base"] = self.base
        if self.combo is not None:
            result["combo"] = self.combo.to_dict()
        if self.falloff is not None:
            result["falloff"] = self.falloff.to_dict()
        if self.damage_over_time is not None:
            result["damage_over_time"] = self.damage_over_time.to_dict()
        if self.gauge_scaling is not None:
            result["gauge_scaling"] = self.gauge_scaling.to_dict()
        if self.triggered is not None:
            result["triggered"] = self.triggered.to_dict()
        if self.modifier is not None:
            result["modifier"] = self.modifier.to_dict()
        if self.stack_potency is not None:
            result["stack_potency"] = self.stack_potency.to_dict()
        if self.conditional_potencies:
            result["conditional_potencies"] = {
                entry.condition: entry.potency for entry in self.conditional_potencies
            }
        return result


@dataclass(frozen=True, slots=True)
class Action:
    """One PvE job action extracted from the official guide."""

    name: str
    level: int
    action_type: str
    potency: Potency | None
    description: tuple[str, ...]
    triggers_action: str | None = None
    deploys_actor: str | None = None
    source_actor: str | None = None
    derived_from: str | None = None
    gauge_gains: tuple[GaugeGain, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if self.level <= 0:
            raise ValueError("level must be positive")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "level": self.level,
            "type": self.action_type,
            "potency": self.potency.to_dict() if self.potency is not None else None,
            "description": list(self.description),
        }
        if self.triggers_action is not None:
            result["triggers_action"] = self.triggers_action
        if self.deploys_actor is not None:
            result["deploys_actor"] = self.deploys_actor
        if self.source_actor is not None:
            result["source_actor"] = self.source_actor
        if self.derived_from is not None:
            result["derived_from"] = self.derived_from
        if self.gauge_gains:
            result["gauge_gains"] = [gain.to_dict() for gain in self.gauge_gains]
        return result
