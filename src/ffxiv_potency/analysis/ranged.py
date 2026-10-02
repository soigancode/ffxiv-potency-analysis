"""Consecutive ranged GCDs with adjacent GCDs and every recorded cast gap."""

from dataclasses import dataclass

from .events import _event_name


@dataclass(frozen=True, slots=True)
class RangedChain:
    seconds: float
    previous: str | None
    previous_gap: float | None
    following: str | None
    following_gap: float | None
    actions: tuple[str, ...]
    gaps: tuple[float, ...]


def ranged_chains(gcds, names, start, ranged_packets):
    chains = []
    index = 0
    while index < len(gcds):
        def ranged(i):
            return (gcds[i].get("packetID"), gcds[i].get("abilityGameID")) in ranged_packets

        if not ranged(index):
            index += 1
            continue
        last = index
        while last + 1 < len(gcds) and ranged(last + 1):
            last += 1
        previous = gcds[index - 1] if index else None
        following = gcds[last + 1] if last + 1 < len(gcds) else None
        chains.append(RangedChain(
            (gcds[index]["timestamp"] - start) / 1000,
            _event_name(previous, names) if previous else None,
            (gcds[index]["timestamp"] - previous["timestamp"]) / 1000 if previous else None,
            _event_name(following, names) if following else None,
            (following["timestamp"] - gcds[last]["timestamp"]) / 1000 if following else None,
            tuple(_event_name(gcds[i], names) for i in range(index, last + 1)),
            tuple((gcds[i + 1]["timestamp"] - gcds[i]["timestamp"]) / 1000
                  for i in range(index, last)),
        ))
        index = last + 1
    return tuple(chains)
