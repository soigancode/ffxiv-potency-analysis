"""Typed results returned by combat-log analysis."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActionSummary:
    name: str
    hits: int
    potency_min: float
    potency_max: float
    uses: int | None = None


@dataclass(frozen=True, slots=True)
class AutoAttackSummary:
    name: str
    hits: int
    estimated_delay_seconds: float
    weapon_delay_seconds: float
    potency_per_hit: float
    total_potency: float


@dataclass(frozen=True, slots=True)
class PetDeploymentSummary:
    actor: str
    timestamp_seconds: float
    gauge: str
    gauge_spent: int
    potency_min: float = 0.0
    potency_max: float = 0.0
    missing_finishers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HitOutcomeSummary:
    normal: int
    critical: int
    direct: int
    critical_direct: int
    unknown: int = 0

    @property
    def known_hits(self) -> int:
        return self.normal + self.critical + self.direct + self.critical_direct

    @property
    def critical_rate(self) -> float:
        return (self.critical + self.critical_direct) / self.known_hits if self.known_hits else 0

    @property
    def direct_rate(self) -> float:
        return (self.direct + self.critical_direct) / self.known_hits if self.known_hits else 0

    @property
    def critical_direct_rate(self) -> float:
        return self.critical_direct / self.known_hits if self.known_hits else 0


@dataclass(frozen=True, slots=True)
class PotionWindow:
    start_seconds: float | None
    end_seconds: float | None
    observed_start_seconds: float | None = None
    observed_end_seconds: float | None = None
    inferred: bool = False


@dataclass(frozen=True, slots=True)
class PotionSummary:
    uses: int
    potted_potency_min: float
    potted_potency_max: float
    gained_potency_min: float
    gained_potency_max: float
    windows: tuple[PotionWindow, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    fight_name: str
    encounter_id: int | None
    source_name: str
    ndps: float | None
    duration_seconds: float
    raw_damage_events: int
    landed_damage_events: int
    matched_damage_events: int
    potency_min: float
    potency_max: float
    actions: tuple[ActionSummary, ...]
    auto_attacks: tuple[AutoAttackSummary, ...]
    pet_deployments: tuple[PetDeploymentSummary, ...]
    hit_outcomes: HitOutcomeSummary
    potion: PotionSummary
    unmatched: tuple[tuple[str, int], ...]
    ghosted: tuple[tuple[str, int], ...]
    rdps: float | None = None
    luck_score: float = 0.0
    adjusted_luck_score: float = 0.0
    luck_baseline: float = 0.0
    critical_gear_baseline: float = 0.0
    direct_gear_baseline: float = 0.0
    direct_critical_gear_baseline: float = 0.0
    ghosted_times: tuple[tuple[str, tuple[float, ...]], ...] = ()

    @property
    def pps_min(self) -> float:
        return self.potency_min / self.duration_seconds

    @property
    def pps_max(self) -> float:
        return self.potency_max / self.duration_seconds
