"""Fight or Flight coverage using the potency calculation's resolved snapshots."""

from dataclasses import dataclass

from .buffs import FIGHT_OR_FLIGHT

ALIGNMENT_ACTIONS = (
    "Goring Blade", "Imperator", "Confiteor", "Blade of Faith", "Blade of Truth",
    "Blade of Valor", "Blade of Honor", "Circle of Scorn", "Expiacion",
)


@dataclass(frozen=True, slots=True)
class PldAlignmentWindow:
    start_seconds: float
    end_seconds: float
    inside_potency: float
    outside_potency: float


@dataclass(frozen=True, slots=True)
class PldAlignmentFinding:
    seconds: float
    action: str
    potency: float
    potential_gain: float
    window_start_seconds: float | None
    window_end_seconds: float | None


@dataclass(frozen=True, slots=True)
class PldAlignment:
    inside_potency: float
    outside_potency: float
    windows: tuple[PldAlignmentWindow, ...]
    outside: tuple[PldAlignmentFinding, ...]


def summarize_alignment(rows, buff_windows, start, end, strength: float) -> PldAlignment:
    """Group attacks by the nearest buff window; retain explicit packet evidence.

    Row potency excludes Fight or Flight, but retains other calculated modifiers.
    Multiple targets and periodic ticks sharing an application snapshot are combined.
    """
    windows = [(a, min(b, end)) for a, b, _ in buff_windows.get(FIGHT_OR_FLIGHT, ())
               if a < end and b > start]
    totals = [[0.0, 0.0] for _ in windows]
    inside = outside = 0.0
    findings = {}
    for time, name, potency, buffed in rows:
        if name not in ALIGNMENT_ACTIONS:
            continue
        index = min(range(len(windows)), key=lambda i: (
            max(windows[i][0] - time, time - windows[i][1], 0),
            abs(time - windows[i][0]),
        )) if windows else None
        if buffed:
            inside += potency
        else:
            outside += potency
            key = (time, name, index)
            findings[key] = findings.get(key, 0.0) + potency
        if index is not None:
            totals[index][0 if buffed else 1] += potency
    return PldAlignment(
        inside, outside,
        tuple(PldAlignmentWindow((a - start) / 1000, (b - start) / 1000, *total)
              for (a, b), total in zip(windows, totals)),
        tuple(PldAlignmentFinding(
            (time - start) / 1000, name, potency, potency * (strength - 1),
            (windows[index][0] - start) / 1000 if index is not None else None,
            (windows[index][1] - start) / 1000 if index is not None else None,
        ) for (time, name, index), potency in findings.items()),
    )
