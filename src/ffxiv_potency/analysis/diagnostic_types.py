"""Serializable cross-job execution evidence and job-specific rules."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlignmentRule:
    name: str
    status: str
    actions: tuple[str, ...]
    kind: str = "damage"
    strength: float = 1.0
    duration_ms: int = 20000


@dataclass(frozen=True, slots=True)
class FollowUpRule:
    name: str
    status: str
    actions: tuple[str, ...]
    duration_ms: int = 30000
    charges: int = 1
    requires_hit: bool = True


@dataclass(frozen=True, slots=True)
class AlignmentWindow:
    start_seconds: float
    end_seconds: float
    inside_potency: float
    outside_potency: float


@dataclass(frozen=True, slots=True)
class OutsideAction:
    action: str
    uses: int
    potency: float
    potential_gain: float


@dataclass(frozen=True, slots=True)
class BurstAlignment:
    name: str
    kind: str
    scope: tuple[str, ...]
    inside_potency: float
    outside_potency: float
    windows: tuple[AlignmentWindow, ...]
    outside: tuple[OutsideAction, ...]
    evidence_available: bool = True


@dataclass(frozen=True, slots=True)
class FollowUpContext:
    seconds: float
    actions: tuple[str, ...]
    outcome: str
    reason: str
