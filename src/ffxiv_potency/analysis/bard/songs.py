"""Bard song durations, Codas, Finale, and Encore."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from ..events import _event_name

SONGS = frozenset({"Mage's Ballad", "Army's Paeon", "The Wanderer's Minuet"})


@dataclass(frozen=True, slots=True)
class BardFinaleSummary:
    timestamp_seconds: float
    coda: int
    encore_hits: int = 0
    encore_potency_min: float = 0.0
    encore_potency_max: float = 0.0


def _bard_coda(
    casts: list[dict[str, Any]], names: dict[int, str], fight_start: float = 0
) -> tuple[dict[tuple[Any, Any], int], tuple[BardFinaleSummary, ...], tuple[tuple[str, int], ...]]:
    """Use distinct songs since the last Finale to reconstruct consumed Coda."""
    songs = SONGS
    coda: dict[int, set[str]] = defaultdict(set)
    last_finale: dict[int, tuple[float, int]] = {}
    encore_coda: dict[tuple[Any, Any], int] = {}
    finales: list[BardFinaleSummary] = []
    song_counts: Counter[str] = Counter()
    for cast in sorted(casts, key=lambda item: item.get("timestamp", 0)):
        actor = cast.get("sourceID")
        timestamp = cast.get("timestamp")
        if not isinstance(actor, int) or not isinstance(timestamp, (int, float)):
            continue
        name = _event_name(cast, names)
        if name in songs:
            coda[actor].add(name)
            song_counts[name] += 1
        elif name == "Radiant Finale":
            last_finale[actor] = float(timestamp), len(coda[actor])
            finales.append(BardFinaleSummary((timestamp - fight_start) / 1000, len(coda[actor])))
            coda[actor].clear()
        elif name == "Radiant Encore":
            finale = last_finale.get(actor)
            if finale is not None and 0 <= timestamp - finale[0] <= 30000 and 1 <= finale[1] <= 3:
                encore_coda[(cast.get("packetID"), cast.get("abilityGameID"))] = finale[1]
    return encore_coda, tuple(finales), tuple(sorted(song_counts.items()))

def _bard_song_durations(
    casts: list[dict[str, Any]], buffs: list[dict[str, Any]],
    names: dict[int, str], source_id: int | None, fight_end: float,
) -> tuple[tuple[str, float], ...]:
    """Average each song's active time, including a final shortened song."""
    songs = SONGS
    song_casts = sorted(
        (cast for cast in casts
         if cast.get("sourceID") == source_id
         and _event_name(cast, names) in songs
         and isinstance(cast.get("timestamp"), (int, float))),
        key=lambda cast: cast["timestamp"],
    )
    removals: dict[int, list[float]] = defaultdict(list)
    for buff in buffs:
        if (isinstance(buff, dict) and buff.get("targetID") == source_id
                and buff.get("type") == "removebuff"
                and isinstance(buff.get("abilityGameID"), int)
                and isinstance(buff.get("timestamp"), (int, float))):
            removals[buff["abilityGameID"]].append(float(buff["timestamp"]))
    durations: dict[str, list[float]] = defaultdict(list)
    for index, cast in enumerate(song_casts):
        started = float(cast["timestamp"])
        ended = min(fight_end, started + 45000)
        if index + 1 < len(song_casts):
            ended = min(ended, float(song_casts[index + 1]["timestamp"]))
        removal = min((time for time in removals.get(cast.get("abilityGameID"), ())
                       if time >= started), default=ended)
        ended = min(ended, removal)
        durations[_event_name(cast, names)].append(max(0, ended - started) / 1000)
    return tuple((song, sum(values) / len(values)) for song, values in sorted(durations.items()))
