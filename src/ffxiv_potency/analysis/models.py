"""Typed results returned by combat-log analysis."""

from dataclasses import dataclass

from .brd.dots import BrdDotActionSummary
from .brd.songs import BrdFinaleSummary
from .mch.wildfire import MchWildfireSummary
from .penalties import DamagePenaltySummary, StatusWindow


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
    gauge_assumed: bool = False
    potency_min: float = 0.0
    potency_max: float = 0.0
    mch_missing_finishers: tuple[str, ...] = ()
    mch_overdrive_seconds: float | None = None
    mch_gauge_inferred: bool = False
    mch_prepull: bool = False


@dataclass(frozen=True, slots=True)
class BrdOutsideExpectedHit:
    normalized_damage: float
    potency: float
    lower_damage: float
    upper_damage: float


@dataclass(frozen=True, slots=True)
class ReducedDamageHit:
    seconds: float
    action: str
    damage: float
    overkill: float
    target: str = ""


@dataclass(frozen=True, slots=True)
class BrdApexUseEstimate:
    seconds: float
    hits: int
    gauge: int
    plausible_gauges: tuple[int, ...]
    potency: float | None = None
    packet: tuple[int | None, int | None] | None = None


@dataclass(frozen=True, slots=True)
class BrdPitchHitEstimate:
    seconds: float
    best_fit: str
    plausible_fits: tuple[str, ...]
    outside_expected: bool
    distance_from_bound_percent: float | None = None


@dataclass(frozen=True, slots=True)
class BrdPotencyEstimateSummary:
    action: str
    estimated_hits: int
    uncertain_hits: int
    uncertainty_potency: float
    outside_expected_hits: int = 0
    outside_expected_details: tuple[BrdOutsideExpectedHit, ...] = ()
    apex_uses: tuple[BrdApexUseEstimate, ...] = ()
    pitch_uncertain_hits: tuple[BrdPitchHitEstimate, ...] = ()
    weak_reference_hits: int = 0


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
class ConsumableIdentity:
    name: str
    recorded: bool


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
    item: ConsumableIdentity | None = None


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
    dps: float | None = None
    luck_score: float = 0.0
    adjusted_luck_score: float = 0.0
    luck_baseline: float = 0.0
    critical_gear_baseline: float = 0.0
    direct_gear_baseline: float = 0.0
    direct_critical_gear_baseline: float = 0.0
    ghosted_times: tuple[tuple[str, tuple[float, ...]], ...] = ()
    ghosted_targets: tuple[tuple[str, tuple[tuple[float, str], ...]], ...] = ()
    ghosted_target_low_hp: tuple[tuple[str, tuple[tuple[float, int], ...]], ...] = ()
    ghosted_ending_times: tuple[tuple[str, tuple[tuple[float, str], ...]], ...] = ()
    reduced_damage_hits: tuple[ReducedDamageHit, ...] = ()
    mch_wildfires: tuple[MchWildfireSummary, ...] = ()
    brd_potency_estimates: tuple[BrdPotencyEstimateSummary, ...] = ()
    brd_songs: tuple[tuple[str, int], ...] = ()
    brd_song_durations: tuple[tuple[str, float], ...] = ()
    brd_finales: tuple[BrdFinaleSummary, ...] = ()
    brd_dots: tuple[BrdDotActionSummary, ...] = ()
    food: ConsumableIdentity | None = None
    food_missing_windows: tuple[tuple[float, float], ...] = ()
    damage_penalties: tuple[DamagePenaltySummary, ...] = ()
    kill: bool | None = None
    status_windows: tuple[StatusWindow, ...] = ()
    echo_status: str | None = None
    party_bonus_percent: int | None = None
    played_patch: str | None = None
    patch_source: str | None = None
    actions_since: str | None = None
    gear_id: str | None = None
    gear_name: str | None = None
    gear_source: str | None = None

    @property
    def pps_min(self) -> float:
        return self.potency_min / self.duration_seconds

    @property
    def pps_max(self) -> float:
        return self.potency_max / self.duration_seconds
