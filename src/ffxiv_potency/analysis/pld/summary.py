"""Evidence-based Paladin ready effects, spell uses and burst follow-ups."""

from collections import Counter
from dataclasses import dataclass

from ..cooldown_timing import CooldownTiming
from ..events import _event_name
from ..execution import ReadyUse, ready_summary
from ..ranged import RangedChain, ranged_chains
from .alignment import PldAlignment, summarize_alignment
from .buffs import fight_or_flight_strength
from .cooldowns import summarize_cooldowns
from .state import BLADES, PldSpellState


@dataclass(frozen=True, slots=True)
class PldFollowUp:
    name: str
    casts: int
    hits: int
    potency: float


@dataclass(frozen=True, slots=True)
class PldBurst:
    seconds: float
    trigger: str
    follow_ups: tuple[PldFollowUp, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PldDotSummary:
    applications: int
    ticks: int
    application_potency: float
    tick_potency: float


@dataclass(frozen=True, slots=True)
class PldSummary:
    ready: tuple[ReadyUse, ...]
    spell_counts: tuple[tuple[str, str, str, int], ...]
    bursts: tuple[PldBurst, ...]
    ranged: tuple[RangedChain, ...]
    circle: PldDotSummary
    holy_spirit_casts: tuple[tuple[float, str], ...] = ()
    alignment: PldAlignment | None = None
    cooldown_timing: tuple[CooldownTiming, ...] = ()


READY = (
    (1003847, "Goring Blade", ("Goring Blade",)),
    (1001902, "Atonement", ("Atonement",)),
    (1003827, "Supplication", ("Supplication",)),
    (1003828, "Sepulchre", ("Sepulchre",)),
    (1003019, "Confiteor", ("Confiteor",)),
    (1003831, "Blade of Honor", ("Blade of Honor",)),
)


def summarize_pld(casts, buffs, life, combatants, names, actions, source, start, end,
                  state: PldSpellState, landed, circle: PldDotSummary,
                  alignment_rows=(), buff_windows=None, targetable=None) -> PldSummary:
    own = sorted((e for e in casts if e.get("sourceID") == source
                  and e.get("type") == "cast" and not e.get("fake")),
                 key=lambda e: e["timestamp"])
    own_buffs = [e for e in buffs if e.get("targetID") == source
                 and e.get("sourceID") in {source, None}]
    initial = {a.get("ability") for c in combatants if c.get("sourceID") == source
               for a in c.get("auras", ())}
    ready = state.ready + tuple(ready_summary(
        (name, names), status, consumers, own, own_buffs, initial, life, source, start, end, 30000,
    ) for status, name, consumers in READY)
    counts = Counter((s.name, s.enhancement, s.cast_kind) for s in state.spells)
    triggers = [e for e in own if _event_name(e, names) in {"Imperator", "Requiescat"}]
    # Carry-over sequences can begin before the downloaded phase.
    if state.spells and state.spells[0].enhancement == "Requiescat" and (
        not triggers or state.spells[0].seconds < (triggers[0]["timestamp"] - start) / 1000
    ):
        triggers.insert(0, {"timestamp": start, "abilityGameID": -1})
    bursts = []
    follow_names = (*BLADES, "Blade of Honor")
    for index, trigger in enumerate(triggers):
        begin = trigger["timestamp"]
        finish = triggers[index + 1]["timestamp"] if index + 1 < len(triggers) else end
        follows = [e for e in own if begin <= e["timestamp"] < finish
                   and _event_name(e, names) in follow_names]
        notes = []
        rows = []
        for name in follow_names:
            cs = [e for e in follows if _event_name(e, names) == name]
            packets = {(e.get("packetID"), e.get("abilityGameID")) for e in cs}
            hits = [value for packet, _, value in landed if packet in packets]
            rows.append(PldFollowUp(name, len(cs), len(hits), sum(hits)))
            if not cs:
                notes.append(f"{name}: no recorded cast")
            elif not hits:
                notes.append(f"{name}: no landed hit")
            for cast in cs:
                delay = (cast["timestamp"] - begin) / 1000
                if delay > 30:
                    notes.append(f"{name}: delayed {delay:.2f}s after burst start")
        packets = {(e.get("packetID"), e.get("abilityGameID")) for e in follows}
        for spell in state.spells:
            if (spell.packet, spell.ability_id) in packets and spell.enhancement == "None":
                notes.append(f"{spell.name}: unenhanced")
        bursts.append(PldBurst((begin - start) / 1000,
                               names.get(trigger["abilityGameID"], "Pre-pull state"),
                               tuple(rows), tuple(notes)))
    gcds = [e for e in own if actions.get(_event_name(e, names), {}).get("type", "").casefold()
            in {"weaponskill", "spell"}]
    ranged = {(e.get("packetID"), e.get("abilityGameID")) for e in gcds
              if _event_name(e, names) == "Shield Lob"}
    first_damage = next((e for e in own if actions.get(_event_name(e, names), {}).get("potency")), None)
    opener_packet = (first_damage.get("packetID"), first_damage.get("abilityGameID")) if first_damage else None
    ranged.update((s.packet, s.ability_id) for s in state.spells
                  if s.name == "Holy Spirit" and s.cast_kind == "hard cast"
                  and (s.packet, s.ability_id) != opener_packet)
    return PldSummary(ready, tuple((*key, n) for key, n in sorted(counts.items())),
                      tuple(bursts), ranged_chains(gcds, names, start, ranged), circle,
                      tuple((s.seconds, s.cast_kind) for s in state.spells
                            if s.name == "Holy Spirit"),
                      summarize_alignment(alignment_rows, buff_windows or {}, start, end,
                                          fight_or_flight_strength(actions))
                      if buff_windows is not None else None,
                      summarize_cooldowns(own, actions, names, life, source, start, end, targetable)
                      if targetable is not None else ())
