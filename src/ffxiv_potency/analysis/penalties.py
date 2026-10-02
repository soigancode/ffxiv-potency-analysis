"""Global revival penalties and encounter-specific damage penalties."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .config import reference_path
from .errors import AnalysisError
from .events import _has_buff, _load_json
from .profiles import _CombatProfile, _player_main_stat_factor

_REVIVAL_EFFECTS = {1000043: ("Weakness", 25), 1000044: ("Brink of Death", 50)}
_REVIVAL_DURATION_MS = 100_000
_TRANSCENDENT_BUFF_ID = 1000418
_REVIVAL_STATUS_DELAY_MS = 1_000


@dataclass(frozen=True, slots=True)
class DamagePenaltySummary:
    name: str
    multiplier: float | None
    first_observed_seconds: float
    last_observed_seconds: float
    affected_hits: int
    main_stat_reduction: int | None = None
    lost_potency_min: float | None = None
    lost_potency_max: float | None = None
    hit_losses: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class StatusWindow:
    name: str
    start_seconds: float
    end_seconds: float
    end_reason: str
    refresh_seconds: tuple[float, ...] = ()


_TRACKED_STATUSES = {"Weakness", "Brink of Death", "Damage Down"}


def summarize_status_windows(
    debuffs: list[dict[str, Any]], life: list[dict[str, Any]],
    ability_names: dict[int, str], source_id: int | None,
    start: float, end: float, casts: list[dict[str, Any]] | None = None,
    revival_buffs: list[dict[str, Any]] | None = None,
    *, encounter_overkills: list[dict[str, Any]] | None = None,
    actors: dict[int, dict[str, Any]] | None = None,
) -> tuple[StatusWindow, ...]:
    """Use revival statuses; bound missing events by the next player cast."""
    if source_id is None:
        return ()
    active: dict[int | str, float] = {}
    expires_at: dict[int, float] = {}
    refreshes: dict[int, list[float]] = defaultdict(list)
    windows: list[StatusWindow] = []
    # FF Logs can represent a renewed debuff as a removal immediately followed
    # by another application at the same timestamp.
    replacements = {
        (event.get("abilityGameID"), event.get("timestamp"))
        for event in debuffs
        if event.get("targetID") == source_id
        and event.get("type") in {"applydebuff", "refreshdebuff"}
        and isinstance(event.get("abilityGameID"), int)
        and ability_names.get(event["abilityGameID"]) == "Damage Down"
    }
    events = sorted(
        (*debuffs, *life, *(casts or ()), *(revival_buffs or ())),
        key=lambda event: (
            event.get("timestamp", 0),
            0 if event.get("type") == "resurrect" else 1,
        ),
    )
    for event in events:
        kind = event.get("type")
        if (event.get("sourceID") if kind == "cast" else event.get("targetID")) != source_id:
            continue
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)) or not start <= timestamp <= end:
            continue
        ability_id = event.get("abilityGameID")
        name = ability_names.get(ability_id) if isinstance(ability_id, int) else None
        if kind == "death":
            for status_id in list(active):
                if isinstance(status_id, int):
                    begun = active.pop(status_id)
                    windows.append(StatusWindow(
                        ability_names.get(status_id, "Unknown"),
                        (begun - start) / 1000, (timestamp - start) / 1000, "death",
                        tuple(refreshes.pop(status_id, ())),
                    ))
                    expires_at.pop(status_id, None)
            active.setdefault("dead", float(timestamp))
        elif kind == "cast":
            begun = active.get("dead")
            if begun is not None and timestamp > begun + 1000:
                active.pop("dead")
                windows.append(StatusWindow(
                    "Dead", (begun - start) / 1000,
                    (timestamp - start) / 1000,
                    "revived by next cast; exact time unknown",
                ))
        elif kind == "resurrect":
            begun = active.pop("dead", None)
            if begun is not None:
                windows.append(StatusWindow("Dead", (begun - start) / 1000,
                                            (timestamp - start) / 1000, "resurrected"))
        elif kind in {"applybuff", "refreshbuff"} and ability_id == _TRANSCENDENT_BUFF_ID:
            begun = active.get("dead")
            # A normal revival may also apply Transcendent. Allow a nearby
            # Weakness/Brink event to identify that revival instead of LB3.
            has_revival_penalty = begun is not None and any(
                status.get("targetID") == source_id
                and status.get("type") in {"applydebuff", "refreshdebuff", "applydebuffstack"}
                and status.get("abilityGameID") in _REVIVAL_EFFECTS
                and isinstance(status.get("timestamp"), (int, float))
                and begun <= status["timestamp"] <= timestamp + _REVIVAL_STATUS_DELAY_MS
                for status in debuffs
            )
            if begun is not None and not has_revival_penalty:
                active.pop("dead")
                windows.append(StatusWindow(
                    "Dead", (begun - start) / 1000, (timestamp - start) / 1000,
                    "revived: Healer LB3",
                ))
        elif name in _TRACKED_STATUSES and isinstance(ability_id, int):
            if kind in {"applydebuff", "refreshdebuff", "applydebuffstack"}:
                # FF Logs can omit the resurrect event but records the status
                # applied on revival. Its application marks the revival event.
                if name in {"Weakness", "Brink of Death"}:
                    begun = active.pop("dead", None)
                    if begun is not None:
                        windows.append(StatusWindow(
                            "Dead", (begun - start) / 1000,
                            (timestamp - start) / 1000,
                            "revived: " + name + " applied",
                        ))
                if ability_id in active and name == "Damage Down" and timestamp > active[ability_id]:
                    at = (timestamp - start) / 1000
                    if not refreshes[ability_id] or refreshes[ability_id][-1] != at:
                        refreshes[ability_id].append(at)
                else:
                    active.setdefault(ability_id, float(timestamp))
                duration = event.get("duration")
                if name == "Damage Down" and isinstance(duration, (int, float)) and duration > 0:
                    expires_at[ability_id] = timestamp + duration
            elif kind in {"removedebuff", "removedebuffstack"}:
                if name == "Damage Down" and (ability_id, timestamp) in replacements:
                    continue
                begun = active.pop(ability_id, None)
                if begun is not None:
                    expired = (
                        (name in {"Weakness", "Brink of Death"}
                         and abs(timestamp - begun - _REVIVAL_DURATION_MS) <= 1_000)
                        or (name == "Damage Down" and ability_id in expires_at
                            and abs(timestamp - expires_at[ability_id]) <= 1_000)
                    )
                    boss_defeated = name == "Damage Down" and any(
                        hit.get("type") == "damage" and not hit.get("tick")
                        and hit.get("overkill", 0) > 0
                        and isinstance(target_id := hit.get("targetID"), int)
                        and (actors or {}).get(target_id, {}).get("subType") == "Boss"
                        and isinstance(hit.get("timestamp"), (int, float))
                        and 0 <= timestamp - hit["timestamp"] <= 250
                        for hit in encounter_overkills or ()
                    )
                    expires_at.pop(ability_id, None)
                    windows.append(StatusWindow(name, (begun - start) / 1000,
                                                (timestamp - start) / 1000,
                                                "expired" if expired else
                                                "boss defeated" if boss_defeated else
                                                "fight ended" if end - timestamp < 1000
                                                else "removed",
                                                tuple(refreshes.pop(ability_id, ()))))
    for key, begun in active.items():
        if isinstance(key, int):
            name = ability_names.get(key, "Unknown")
        else:
            name = "Dead"
        windows.append(StatusWindow(name, (begun - start) / 1000,
                                    (end - start) / 1000, "fight ended",
                                    tuple(refreshes.pop(key, ())) if isinstance(key, int) else ()))
    return tuple(sorted(windows, key=lambda window: (window.start_seconds, window.name)))


def load_damage_penalties(encounter_id: int | None) -> dict[int, tuple[str, float]]:
    if encounter_id is None:
        return {}
    path = reference_path("encounters", str(encounter_id), "penalties.json")
    if not path.is_file():
        return {}
    document = _load_json(path, dict)
    if document.get("encounter_id") != encounter_id or not isinstance(document.get("effects"), list):
        raise AnalysisError(f"invalid damage penalties for encounter {encounter_id}")
    rules: dict[int, tuple[str, float]] = {}
    for effect in document["effects"]:
        if not isinstance(effect, dict):
            raise AnalysisError(f"invalid damage penalties for encounter {encounter_id}")
        status_id = effect.get("status_id")
        name = effect.get("name")
        factor = effect.get("potency_multiplier")
        if (
            not isinstance(status_id, int) or not isinstance(name, str)
            or not isinstance(factor, (int, float)) or not 0 < factor <= 1
        ):
            raise AnalysisError(f"invalid damage penalties for encounter {encounter_id}")
        rules[status_id] = name, float(factor)
    return rules


def penalty_multiplier(event: dict[str, Any], rules: dict[int, tuple[str, float]]) -> float:
    factor = 1.0
    for status_id, (_, multiplier) in rules.items():
        if _has_buff(event, status_id):
            factor *= multiplier
    return factor


def revival_multiplier(
    event: dict[str, Any], profile: _CombatProfile, *, potted: bool | None = None,
) -> float:
    """Scale potency by the main-stat damage factor under Weakness or Brink.

    These statuses replace one another. Potion presence comes from the damage
    event, except on DoTs where the caller supplies the application snapshot.
    """
    if potted is None:
        potted = _has_buff(event, profile.potion_buff_id)
    dexterity = profile.potted_main_stat if potted else profile.party_main_stat
    for status_id in (1000044, 1000043):
        if _has_buff(event, status_id):
            _, reduction = _REVIVAL_EFFECTS[status_id]
            reduced = dexterity * (100 - reduction) // 100
            return (
                _player_main_stat_factor(
                    reduced, profile.level_main, profile.player_damage_coefficient,
                )
                / _player_main_stat_factor(
                    dexterity, profile.level_main, profile.player_damage_coefficient,
                )
            )
    return 1.0


def summarize_damage_penalties(
    landed: list[dict[str, Any]], rules: dict[int, tuple[str, float]],
    fight_start: float, lost_potency: dict[int, list[float]],
    hit_losses: dict[int, list[tuple[float, float, float]]] | None = None,
) -> tuple[DamagePenaltySummary, ...]:
    observed: dict[int, list[float]] = defaultdict(list)
    for event in landed:
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            continue
        for status_id in rules:
            if _has_buff(event, status_id):
                observed[status_id].append((timestamp - fight_start) / 1000)
    return tuple(
        DamagePenaltySummary(
            name, multiplier, min(times), max(times), len(times),
            lost_potency_min=lost_potency.get(status_id, [0.0, 0.0])[0],
            lost_potency_max=lost_potency.get(status_id, [0.0, 0.0])[1],
            hit_losses=tuple((hit_losses or {}).get(status_id, ())),
        )
        for status_id, times in sorted(observed.items())
        for name, multiplier in (rules[status_id],)
    )


def summarize_revival_penalties(
    landed: list[dict[str, Any]], ability_names: dict[int, str],
    fight_start: float, profile: _CombatProfile,
    lost_potency: dict[int, list[float]],
    hit_losses: dict[int, list[tuple[float, float, float]]] | None = None,
) -> tuple[DamagePenaltySummary, ...]:
    """Show observed Weakness and Brink even when an older archive lacks raw events.

    Damage records give observation bounds only. DoT ticks can retain an old
    snapshot beyond a status's actual removal, so they are excluded here.
    """
    relevant = {status_id: (name, reduction)
                for status_id, (name, reduction) in _REVIVAL_EFFECTS.items()
                if ability_names.get(status_id) == name}
    observed: dict[int, list[float]] = defaultdict(list)
    counts: dict[int, int] = defaultdict(int)
    for event in landed:
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            continue
        for status_id in relevant:
            if _has_buff(event, status_id):
                counts[status_id] += 1
                if not event.get("tick"):
                    observed[status_id].append((timestamp - fight_start) / 1000)
    return tuple(
        DamagePenaltySummary(
            relevant[status_id][0],
            revival_multiplier({"buffs": f"{status_id}."}, profile, potted=False),
            min(times), max(times), counts[status_id], relevant[status_id][1],
            *lost_potency.get(status_id, (0.0, 0.0)),
            hit_losses=tuple((hit_losses or {}).get(status_id, ())),
        )
        for status_id, times in sorted(observed.items())
    )
