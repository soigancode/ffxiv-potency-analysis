"""Job profiles, weapon delays and pet scaling for FF Logs analysis."""

from dataclasses import dataclass

from ..patches import LATEST_KNOWN_PATCH
from .config import reference_path
from .errors import AnalysisError
from .events import _load_json


@dataclass(frozen=True, slots=True)
class _CombatProfile:
    food_buff_id: int
    food_name: str
    unfed_critical_damage_multiplier: float
    unfed_critical_rate: float
    unfed_determination_ratio: float
    potion_buff_id: int
    potion_action_names: tuple[str, ...]
    potion_duration_seconds: int
    player_potion_multiplier: float
    pet_potion_multipliers: dict[str, float]
    critical_damage_multiplier: float
    non_random_damage_actions: frozenset[str]
    auto_base_potency: int
    weapon_damage: int
    action_trait_multiplier: float
    weapon_attribute_modifier: int
    level_main: int
    skill_speed_factor: float
    critical_rate: float
    direct_rate: float


@dataclass(frozen=True, slots=True)
class _PetProfile:
    potency_multiplier: float
    gauge_name: str | None = None
    gauge_minimum: int | None = None
    gauge_maximum: int | None = None
    deployment_action: str | None = None


def _load_weapon_delays(job: str) -> tuple[float, ...]:
    resource = reference_path(job.lower(), "weapon_delays.json")
    if not resource.is_file():
        raise AnalysisError(f"no known weapon delays are configured for job {job!r}")
    values = _load_json(resource, list)
    if not isinstance(values, list) or not values:
        raise AnalysisError(f"no known weapon delays are configured for job {job!r}")
    if not all(isinstance(value, (int, float)) and value > 0 for value in values):
        raise AnalysisError(f"invalid weapon-delay configuration for job {job!r}")
    return tuple(float(value) for value in values)


def _load_pet_profiles(job: str) -> dict[str, _PetProfile]:
    resource = reference_path(job.lower(), LATEST_KNOWN_PATCH, "pet_scaling.json")
    if not resource.is_file():
        return {}
    job_profile = _load_json(resource, dict)
    pets = job_profile.get("pets", {})
    if not isinstance(pets, dict):
        raise AnalysisError(f"invalid pet profiles for job {job!r}")

    profiles: dict[str, _PetProfile] = {}
    for pet_name, profile in pets.items():
        multiplier = profile.get("potency_multiplier") if isinstance(profile, dict) else None
        if (
            not isinstance(pet_name, str)
            or not isinstance(multiplier, (int, float))
            or multiplier <= 0
        ):
            raise AnalysisError(f"invalid pet potency multiplier for job {job!r}")
        gauge = profile.get("gauge")
        if gauge is None:
            profiles[pet_name] = _PetProfile(float(multiplier))
            continue
        if not isinstance(gauge, dict):
            raise AnalysisError(f"invalid pet gauge profile for {pet_name!r}")
        name = gauge.get("name")
        minimum = gauge.get("minimum")
        maximum = gauge.get("maximum")
        deployment = gauge.get("deployment_action")
        if not (
            isinstance(name, str)
            and isinstance(minimum, int)
            and isinstance(maximum, int)
            and 0 < minimum <= maximum
            and isinstance(deployment, str)
        ):
            raise AnalysisError(f"invalid pet gauge profile for {pet_name!r}")
        profiles[pet_name] = _PetProfile(float(multiplier), name, minimum, maximum, deployment)
    return profiles


def _pet_main_stat_factor(
    dexterity: int,
    attribute_modifier: int,
    *,
    level_main: int,
    level_divisor: int,
    coefficient: int,
) -> int:
    modified = dexterity * attribute_modifier // 100
    return coefficient * (modified - level_main) // level_divisor + 100


def _player_main_stat_factor(dexterity: int, level_main: int, coefficient: int) -> int:
    """Non-tank action-damage main-stat factor in hundredths (level 100: 237/440)."""
    return 100 + coefficient * (dexterity - level_main) // level_main


def _critical_damage_multiplier(critical_hit: int, level_sub: int, level_divisor: int) -> float:
    """Calculate tiered critical-hit strength for the configured level."""
    return (1400 + 200 * (critical_hit - level_sub) // level_divisor) / 1000


def _critical_rate(critical_hit: int, level_sub: int, level_divisor: int) -> float:
    return (50 + 200 * (critical_hit - level_sub) // level_divisor) / 1000


def _determination_factor(determination: int, level_main: int, level_divisor: int) -> float:
    return (1000 + 140 * (determination - level_main) // level_divisor) / 1000


def _load_combat_profile(job: str, action_document: dict | None = None) -> _CombatProfile:
    resource = reference_path(job.lower(), LATEST_KNOWN_PATCH, "combat_profile.json")
    if not resource.is_file():
        raise AnalysisError(f"no combat profile is configured for job {job!r}")
    profile = _load_json(resource, dict)
    food_reference = profile.get("food")
    if not isinstance(food_reference, str) or not food_reference.startswith("food/"):
        raise AnalysisError(f"invalid food reference for job {job!r}")
    food = _load_json(reference_path("consumables", food_reference), dict)
    food_bonuses = food.get("bonuses")
    if (
        not isinstance(food.get("buff_id"), int)
        or not isinstance(food.get("name"), str)
        or food.get("quality") != "HQ"
        or not isinstance(food_bonuses, dict)
    ):
        raise AnalysisError(f"invalid HQ food for job {job!r}")
    food_crit = food_bonuses.get("critical_hit")
    food_det = food_bonuses.get("determination")
    if not isinstance(food_crit, dict) or not isinstance(food_det, dict):
        raise AnalysisError(f"missing critical hit or determination food bonus for job {job!r}")
    dexterity = profile.get("dexterity", {})
    stats = profile.get("secondary_stats", {})
    modifiers = profile.get("attribute_modifiers", {})
    potion_reference = profile.get("potion")
    if not isinstance(potion_reference, str) or not potion_reference.startswith("potions/"):
        raise AnalysisError(f"invalid potion reference for job {job!r}")
    potion = _load_json(reference_path("consumables", potion_reference), dict)
    bonuses = potion.get("bonuses")
    dexterity_bonus = bonuses.get("dexterity") if isinstance(bonuses, dict) else None
    if not isinstance(dexterity_bonus, dict) or potion.get("quality") != "HQ":
        raise AnalysisError(f"invalid HQ potion for job {job!r}")
    luck = profile.get("luck", {})
    required_ints = {
        "level_main": profile.get("level_main"),
        "level_sub": profile.get("level_sub"),
        "level_divisor": profile.get("level_divisor"),
        "coefficient": profile.get("attack_power_coefficient"),
        "player_damage_coefficient": profile.get("player_damage_coefficient"),
        "solo": dexterity.get("solo_unpotted"),
        "party": dexterity.get("party_unpotted"),
        "potted": dexterity.get("party_potted"),
        "player_modifier": modifiers.get("player"),
        "potion_cap": dexterity_bonus.get("cap"),
        "potion_percent": dexterity_bonus.get("percent"),
        "buff_id": potion.get("buff_id"),
        "potion_duration": potion.get("duration_seconds"),
        "critical_hit": stats.get("critical_hit"),
        "determination": stats.get("determination"),
        "food_crit_cap": food_crit.get("cap"),
        "food_crit_percent": food_crit.get("percent"),
        "food_det_cap": food_det.get("cap"),
        "food_det_percent": food_det.get("percent"),
        "direct_hit": stats.get("direct_hit"),
        "auto_base_potency": profile.get("auto_attack", {}).get("base_potency"),
        "weapon_damage": profile.get("auto_attack", {}).get("weapon_damage"),
        "skill_speed": stats.get("skill_speed"),
    }
    if not all(isinstance(value, int) and value > 0 for value in required_ints.values()):
        raise AnalysisError(f"invalid combat profile for job {job!r}")
    potion_gain = min(
        required_ints["party"] * required_ints["potion_percent"] // 100,
        required_ints["potion_cap"],
    )
    if required_ints["potted"] != required_ints["party"] + potion_gain:
        raise AnalysisError(f"potted Dexterity does not match the HQ potion for job {job!r}")
    for stat, label in (("critical_hit", "crit"), ("determination", "det")):
        unfed = required_ints[stat] - required_ints[f"food_{label}_cap"]
        if min(
            unfed * required_ints[f"food_{label}_percent"] // 100,
            required_ints[f"food_{label}_cap"],
        ) != required_ints[f"food_{label}_cap"]:
            raise AnalysisError(f"configured {stat} must include its capped HQ food bonus")
    # Synthetic/older action snapshots without traits use the bundled guide.
    if action_document is None or "traits" not in action_document:
        guide = _load_json(reference_path(job.lower(), LATEST_KNOWN_PATCH, "actions.json"), dict)
    else:
        guide = action_document
    traits = guide.get("traits")
    level = profile.get("level")
    if not isinstance(level, int) or not isinstance(traits, list):
        raise AnalysisError(f"missing action damage traits for job {job!r}")
    eligible = [
        trait for trait in traits
        if isinstance(trait, dict)
        and isinstance(trait.get("name"), str)
        and trait["name"].startswith("Increased Action Damage")
        and isinstance(trait.get("level"), int)
        and trait["level"] <= level
    ]
    strongest = max(eligible, key=lambda trait: trait["level"], default=None)
    trait_multiplier = strongest.get("action_damage_multiplier") if strongest else None
    if not isinstance(trait_multiplier, (int, float)) or trait_multiplier <= 0:
        raise AnalysisError(f"missing usable action damage trait for job {job!r} at level {level}")
    action_names = potion.get("action_names")
    if not isinstance(action_names, list) or not all(
        isinstance(name, str) for name in action_names
    ):
        raise AnalysisError(f"invalid potion action names for job {job!r}")
    non_random_actions = luck.get("non_random_damage_actions")
    if not isinstance(non_random_actions, list) or not all(
        isinstance(name, str) for name in non_random_actions
    ):
        raise AnalysisError(f"invalid non-random damage actions for job {job!r}")

    factor_args = {
        "level_main": required_ints["level_main"],
        "level_divisor": required_ints["level_divisor"],
        "coefficient": required_ints["coefficient"],
    }
    player_before = _player_main_stat_factor(
        required_ints["party"], required_ints["level_main"],
        required_ints["player_damage_coefficient"],
    )
    player_after = _player_main_stat_factor(
        required_ints["potted"], required_ints["level_main"],
        required_ints["player_damage_coefficient"],
    )
    pet_multipliers = {}
    for actor, modifier in modifiers.items():
        if actor == "player":
            continue
        if not isinstance(modifier, int) or modifier <= 0:
            raise AnalysisError(f"invalid attribute modifier for {actor!r}")
        pet_before = _pet_main_stat_factor(required_ints["solo"], modifier, **factor_args)
        pet_gain = min(
            required_ints["solo"] * required_ints["potion_percent"] // 100,
            required_ints["potion_cap"],
        )
        pet_after = _pet_main_stat_factor(required_ints["solo"] + pet_gain, modifier, **factor_args)
        pet_multipliers[actor] = pet_after / pet_before
    return _CombatProfile(
        food_buff_id=food["buff_id"],
        food_name=f"{food['name']} [HQ]",
        unfed_critical_damage_multiplier=_critical_damage_multiplier(
            required_ints["critical_hit"] - required_ints["food_crit_cap"],
            required_ints["level_sub"], required_ints["level_divisor"],
        ),
        unfed_critical_rate=_critical_rate(
            required_ints["critical_hit"] - required_ints["food_crit_cap"],
            required_ints["level_sub"], required_ints["level_divisor"],
        ),
        unfed_determination_ratio=(
            _determination_factor(required_ints["determination"], required_ints["level_main"],
                                  required_ints["level_divisor"])
            / _determination_factor(required_ints["determination"] - required_ints["food_det_cap"],
                                    required_ints["level_main"], required_ints["level_divisor"])
        ),
        potion_buff_id=required_ints["buff_id"],
        potion_action_names=tuple(action_names),
        potion_duration_seconds=required_ints["potion_duration"],
        player_potion_multiplier=player_after / player_before,
        pet_potion_multipliers=pet_multipliers,
        critical_damage_multiplier=_critical_damage_multiplier(
            required_ints["critical_hit"],
            required_ints["level_sub"],
            required_ints["level_divisor"],
        ),
        non_random_damage_actions=frozenset(non_random_actions),
        auto_base_potency=required_ints["auto_base_potency"],
        weapon_damage=required_ints["weapon_damage"],
        action_trait_multiplier=float(trait_multiplier),
        weapon_attribute_modifier=required_ints["player_modifier"],
        level_main=required_ints["level_main"],
        skill_speed_factor=(
            1000
            + 130
            * (required_ints["skill_speed"] - required_ints["level_sub"])
            // required_ints["level_divisor"]
        )
        / 1000,
        critical_rate=_critical_rate(
            required_ints["critical_hit"], required_ints["level_sub"],
            required_ints["level_divisor"],
        ),
        direct_rate=(
            550
            * (required_ints["direct_hit"] - required_ints["level_sub"])
            // required_ints["level_divisor"]
        )
        / 1000,
    )
