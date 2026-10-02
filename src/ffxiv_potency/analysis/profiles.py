"""Job profiles, weapon delays and pet scaling for FF Logs analysis."""

from dataclasses import dataclass
from pathlib import Path

from ..datasets import job_code, load_manifest, select_set
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
    guaranteed_direct_multiplier: float
    unfed_guaranteed_direct_multiplier: float
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
    party_main_stat: int
    potted_main_stat: int
    player_damage_coefficient: int


@dataclass(frozen=True, slots=True)
class _PetProfile:
    potency_multiplier: float
    gauge_name: str | None = None
    gauge_minimum: int | None = None
    gauge_maximum: int | None = None
    deployment_action: str | None = None


def _load_weapon_delays(job: str) -> tuple[float, ...]:
    resource = reference_path("jobs", job_code(job), "weapon_delays.json")
    if not resource.is_file():
        raise AnalysisError(f"no known weapon delays are configured for job {job!r}")
    values = _load_json(resource, list)
    if not isinstance(values, list) or not values:
        raise AnalysisError(f"no known weapon delays are configured for job {job!r}")
    if not all(isinstance(value, (int, float)) and value > 0 for value in values):
        raise AnalysisError(f"invalid weapon-delay configuration for job {job!r}")
    return tuple(float(value) for value in values)


def _load_pet_profiles(job: str, resource: Path | None = None) -> dict[str, _PetProfile]:
    manifest, root = load_manifest(job)
    rows = manifest["pet_scaling_sets"]
    resource = resource or (root / select_set(manifest, "pet_scaling_sets", LATEST_KNOWN_PATCH)["file"] if rows else root / "no-pets.json")
    if resource is None or not resource.is_file():
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


def _guaranteed_direct_multiplier(direct_hit: int, determination: int,
                                  level_main: int, level_sub: int, level_divisor: int) -> float:
    """Guaranteed DH converts its attribute into an additive determination term."""
    determination_factor = _determination_factor(determination, level_main, level_divisor)
    direct_bonus = max(0, 140 * (direct_hit - level_sub) // level_divisor) / 1000
    return (determination_factor + direct_bonus) / determination_factor


def _load_combat_profile(
    job: str, action_document: dict | None = None, *, party_bonus_percent: int = 5,
    gear_path: Path | None = None,
) -> _CombatProfile:
    if not isinstance(party_bonus_percent, int) or not 1 <= party_bonus_percent <= 5:
        raise AnalysisError(f"invalid party bonus {party_bonus_percent!r}%")
    if gear_path is None:
        manifest, root = load_manifest(job)
        gear_path = Path(root / str(select_set(manifest, "gear_sets", LATEST_KNOWN_PATCH)["file"]))
    gear = _load_json(gear_path, dict)
    profile_name = gear.get("combat_profile")
    if not isinstance(profile_name, str):
        raise AnalysisError(f"missing combat profile for gear {gear_path}")
    resource = gear_path.parent.parent / profile_name
    if not resource.resolve().is_relative_to(gear_path.parent.parent.resolve()) or not resource.is_file():
        raise AnalysisError(f"invalid combat profile for gear {gear_path}")
    profile = _load_json(resource, dict)
    if profile.get("level") != gear.get("level"):
        raise AnalysisError("gear and combat model have different levels")
    main_stat = profile.get("main_stat", "dexterity")
    if main_stat not in {"strength", "dexterity"}:
        raise AnalysisError(f"unsupported main stat {main_stat!r}")
    if gear_path is not None:
        profile["food"] = gear["food"]
        profile["potion"] = gear["potion"]
        solo = gear[f"solo_{main_stat}"]
        party = solo * 105 // 100
        potion_data = _load_json(reference_path("consumables", gear["potion"]), dict)
        bonus = potion_data["bonuses"][main_stat]
        profile[main_stat] = {"solo_unpotted": solo, "party_unpotted": party,
                                "party_potted": party + min(party * bonus["percent"] // 100, bonus["cap"])}
        profile["secondary_stats"] = {stat: gear[stat] for stat in
                                      ("critical_hit", "direct_hit", "determination", "skill_speed")}
        profile["auto_attack"] = {**profile["auto_attack"], "weapon_damage": gear["weapon_damage"]}
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
    main_stats = profile.get(main_stat, {})
    stats = profile.get("secondary_stats", {})
    modifiers = profile.get("attribute_modifiers", {})
    potion_reference = profile.get("potion")
    if not isinstance(potion_reference, str) or not potion_reference.startswith("potions/"):
        raise AnalysisError(f"invalid potion reference for job {job!r}")
    potion = _load_json(reference_path("consumables", potion_reference), dict)
    bonuses = potion.get("bonuses")
    main_stat_bonus = bonuses.get(main_stat) if isinstance(bonuses, dict) else None
    if not isinstance(main_stat_bonus, dict) or potion.get("quality") != "HQ":
        raise AnalysisError(f"invalid HQ potion for job {job!r}")
    luck = profile.get("luck", {})
    required_ints = {
        "level_main": profile.get("level_main"),
        "level_sub": profile.get("level_sub"),
        "level_divisor": profile.get("level_divisor"),
        "coefficient": profile.get("attack_power_coefficient"),
        "player_damage_coefficient": profile.get("player_damage_coefficient"),
        "solo": main_stats.get("solo_unpotted"),
        "party": main_stats.get("party_unpotted"),
        "potted": main_stats.get("party_potted"),
        "player_modifier": modifiers.get("player"),
        "potion_cap": main_stat_bonus.get("cap"),
        "potion_percent": main_stat_bonus.get("percent"),
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
        raise AnalysisError(f"potted {main_stat.title()} does not match the HQ potion for job {job!r}")
    if required_ints["party"] != required_ints["solo"] * 105 // 100:
        raise AnalysisError(f"configured party {main_stat.title()} must include a 5% bonus for job {job!r}")
    party_stat = required_ints["solo"] * (100 + party_bonus_percent) // 100
    potted_stat = party_stat + min(
        party_stat * required_ints["potion_percent"] // 100,
        required_ints["potion_cap"],
    )
    for stat, label in (("critical_hit", "crit"), ("determination", "det")):
        unfed = required_ints[stat] - required_ints[f"food_{label}_cap"]
        if min(
            unfed * required_ints[f"food_{label}_percent"] // 100,
            required_ints[f"food_{label}_cap"],
        ) != required_ints[f"food_{label}_cap"]:
            raise AnalysisError(f"configured {stat} must include its capped HQ food bonus")
    # Synthetic/older action snapshots without traits use the bundled guide.
    if action_document is None or "traits" not in action_document:
        guide = _load_json(load_manifest(job)[1] / select_set(load_manifest(job)[0], "action_sets", LATEST_KNOWN_PATCH)["file"], dict)
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
    trait_multiplier = (
        strongest.get("action_damage_multiplier") if strongest
        else profile.get("action_trait_multiplier")
    )
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
        party_stat, required_ints["level_main"],
        required_ints["player_damage_coefficient"],
    )
    player_after = _player_main_stat_factor(
        potted_stat, required_ints["level_main"],
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
        guaranteed_direct_multiplier=_guaranteed_direct_multiplier(
            required_ints["direct_hit"], required_ints["determination"],
            required_ints["level_main"], required_ints["level_sub"], required_ints["level_divisor"],
        ),
        unfed_guaranteed_direct_multiplier=_guaranteed_direct_multiplier(
            required_ints["direct_hit"], required_ints["determination"] - required_ints["food_det_cap"],
            required_ints["level_main"], required_ints["level_sub"], required_ints["level_divisor"],
        ),
        potion_buff_id=required_ints["buff_id"],
        potion_action_names=tuple(action_names),
        potion_duration_seconds=required_ints["potion_duration"],
        player_potion_multiplier=player_after / player_before,
        party_main_stat=party_stat,
        potted_main_stat=potted_stat,
        player_damage_coefficient=required_ints["player_damage_coefficient"],
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
