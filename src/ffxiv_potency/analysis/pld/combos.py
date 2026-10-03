"""Confirmed landed combo losses, separate from missing bonus evidence."""

from dataclasses import dataclass
from math import isfinite
from statistics import median

from ..damage import landed_fraction
from ..events import _event_name


@dataclass(frozen=True, slots=True)
class PldComboLoss:
    name: str
    hits: int
    potency_lost: float


@dataclass(frozen=True, slots=True)
class PldComboSummary:
    losses: tuple[PldComboLoss, ...]
    unconfirmed_hits: int = 0
    inferred: tuple["PldComboInference", ...] = ()


@dataclass(frozen=True, slots=True)
class PldComboInference:
    name: str
    seconds: float
    comboed: bool
    potency: int
    potency_lost: float
    references: int
    previous_gcd: str | None = None


def combo_potencies(name, actions) -> tuple[int, int] | None:
    if name not in {"Riot Blade", "Royal Authority", "Prominence"}:
        return None
    potency = actions.get(name, {}).get("potency", {})
    combo = potency.get("combo", {}) if isinstance(potency, dict) else {}
    base = potency.get("base") if isinstance(potency, dict) else None
    enhanced = combo.get("potency") if isinstance(combo, dict) else None
    return (base, enhanced) if (isinstance(base, int) and isinstance(enhanced, int)
                              and enhanced > base) else None


def infer_combos(damage, actions, names, source, start, profile,
                 food_missing=()) -> dict[int, PldComboInference]:
    """Require a unique fit to nearby, consistent same-instance physical hits."""
    from ..normalized_damage import normalized_damage

    fixed = {"Fast Blade", "Total Eclipse", "Shield Lob", "Shield Bash", "Goring Blade",
             "Atonement", "Supplication", "Sepulchre"}
    references = {}
    eligible = []
    for event in damage:
        amount, time = event.get("amount"), event.get("timestamp")
        multiplier = event.get("multiplier")
        resources = event.get("targetResources", {})
        if (event.get("sourceID") != source or event.get("type") != "damage"
                or event.get("tick") or event.get("fake") or event.get("hitType") not in {1, 2}
                or event.get("overkill") or not isinstance(amount, (int, float)) or amount <= 0
                or not isinstance(time, (int, float)) or not isinstance(event.get("targetID"), int)
                or not isinstance(multiplier, (int, float)) or multiplier <= 0
                or isinstance(resources, dict) and resources.get("hitPoints") in {0, 1}):
            continue
        value = normalized_damage(
            event, profile.critical_damage_multiplier,
            potion_multiplier=profile.player_potion_multiplier,
            potion_buff_id=profile.potion_buff_id,
            unfed_critical_multiplier=profile.unfed_critical_damage_multiplier,
            unfed_determination_ratio=profile.unfed_determination_ratio,
            food_missing=food_missing, combat_profile=profile,
        )
        if not isfinite(value) or value <= 0:
            continue
        name = _event_name(event, names)
        target = event["targetID"], event.get("targetInstance") or 1
        candidates = combo_potencies(name, actions)
        bonus = event.get("bonusPercent")
        if candidates is not None and not (isinstance(bonus, (int, float)) and bonus >= 0):
            eligible.append((event, name, target, time, value, candidates))
            continue
        potency = (candidates[1 if bonus > 0 else 0] if candidates is not None
                   else actions.get(name, {}).get("potency", {}).get("base") if name in fixed
                   else None)
        if isinstance(potency, int) and potency > 0:
            references.setdefault(target, []).append((time, value / potency))
    inferred = {}
    for event, name, target, time, value, candidates in eligible:
        nearby = sorted((r for r in references.get(target, ()) if abs(r[0] - time) <= 60000),
                        key=lambda r: abs(r[0] - time))[:30]
        if len(nearby) < 3:
            continue
        center = median(r[1] for r in nearby)
        consistent = [r[1] for r in nearby if .935 <= r[1] / center <= 1.065]
        if len(consistent) < 3:
            continue
        measured = value / median(consistent)
        fits = [p for p in candidates if .935 <= measured / p <= 1.065]
        if len(fits) == 1:
            potency = fits[0]
            inferred[id(event)] = PldComboInference(
                name, (time - start) / 1000, potency == candidates[1], potency,
                float(candidates[1] - potency), len(consistent),
            )
    return inferred


def summarize_combos(damage, actions, names, source: int, inferred=None) -> PldComboSummary:
    totals: dict[str, tuple[int, float]] = {}
    unconfirmed = 0
    for event in damage:
        amount = event.get("amount")
        if (event.get("sourceID") != source or event.get("type") != "damage"
                or event.get("tick") or event.get("fake") or event.get("hitType") == 10
                or not isinstance(amount, (int, float)) or amount <= 0):
            continue
        name = _event_name(event, names)
        if name not in {"Riot Blade", "Royal Authority", "Prominence"}:
            continue
        potency = actions.get(name, {}).get("potency", {})
        combo = potency.get("combo", {})
        base, enhanced = potency.get("base"), combo.get("potency")
        if not isinstance(base, int) or not isinstance(enhanced, int) or enhanced <= base:
            continue
        bonus = event.get("bonusPercent")
        if not isinstance(bonus, (int, float)) or bonus < 0:
            if id(event) not in (inferred or {}):
                unconfirmed += 1
        elif bonus == 0:
            hits, loss = totals.get(name, (0, 0.0))
            totals[name] = hits + 1, loss + (enhanced - base) * landed_fraction(event)
    return PldComboSummary(tuple(PldComboLoss(name, hits, loss)
                                 for name, (hits, loss) in sorted(totals.items())), unconfirmed,
                           tuple((inferred or {}).values()))
