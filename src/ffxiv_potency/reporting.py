"""Compact human-readable reports. Formatting never enters calculation caches."""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from textwrap import fill

from .analysis.brd.dots import DOT_NAMES
from .analysis.burst_opportunities import BurstWindow
from .analysis.execution import Coverage
from .analysis.mch.wildfire import MchWildfireSummary
from .analysis.models import AnalysisResult
from .report_document import ACTION_HEADERS, emit_table, emit_text

PLD_POTION_ACTIONS = (
    "Goring Blade", "Imperator", "Circle of Scorn", "Confiteor", "Expiacion", "Intervene",
    "Blade of Faith", "Blade of Truth", "Blade of Valor", "Blade of Honor",
)


def decimal_potency(minimum, maximum):
    return (f"{minimum:,.1f}" if minimum == maximum
            else f"{minimum:,.1f}-{maximum:,.1f}")


def explain_once(text, explanations):
    if text not in explanations:
        emit_text("  " + text)
        explanations.add(text)


def burst_completion(window):
    if window.attributed_followups and window.hold_comparison is None:
        return "n/a"
    if window.held_cleaves and window.best_package_potency is None:
        return "n/a"
    if any(action.expected is None for action in window.actions if action.name != "Infuriate"):
        return "n/a"
    if window.best_package_potency is not None:
        if window.best_package_potency <= 0 or window.actual_package_potency is None:
            return "n/a"
        return f"{window.actual_package_potency / window.best_package_potency:.1%}"
    expected = sum(action.expected or 0 for action in window.actions)
    completed = sum(min(action.package_casts, action.expected or 0) for action in window.actions)
    return f"{completed / expected:.1%}" if expected else "n/a"


def package_action_notes(action):
    notes = [note for note in action.notes if not note.endswith(
        " excluded from comparison; occurred after the first ghost.")]
    if action.excluded_casts:
        count = action.excluded_casts
        notes.append("Excluded from comparison: "
                     + ("cast" if count == 1 else f"{count} casts")
                     + " after the first hit blocked by the HP lock.")
    return ' '.join(notes)


def held_cleave_note(window, comparison, stamp):
    difference = comparison.held_potency - comparison.earlier_potency
    text = (f"Held for cleave at {stamp(comparison.cast_seconds)}: {comparison.targets} targets.\n"
            f"Recorded potency: {comparison.held_potency:,.1f}"
            + (" (unenhanced)." if comparison.name in {'Confiteor', 'Blade of Faith', 'Blade of Truth', 'Blade of Valor'}
               and comparison.enhancement == 'None' else ".")
            + f"\nEarlier in Fight or Flight at {stamp(comparison.earlier_seconds)}: "
            f"{comparison.earlier_potency:,.1f} on 1 target.\n"
            f"Holding {'gained' if difference > 0 else 'lost' if difference < 0 else 'changed'} "
            f"{abs(difference):,.1f} potency.")
    if len(window.held_cleaves) > 1:
        total = sum(c.held_potency - c.earlier_potency for c in window.held_cleaves)
        text += (f"\nHeld follow-ups together: {abs(total):,.1f} potency "
                 f"{'gained' if total > 0 else 'lost' if total < 0 else 'difference'}.")
    if comparison.held_effects:
        text += '\nRecorded buffs: ' + ', '.join(comparison.held_effects) + '.'
    return text


def hold_comparison_note(window, stamp):
    comparison = window.hold_comparison
    if comparison is None:
        return ''
    recorded_best = all(abs(a.recorded_potency - a.proposed_potency) < .05
                        for a in comparison.actions)
    text = 'Held for cleave:\nAction | Inside FoF | Held' if recorded_best else (
        'Hold comparison:\nAction | Inside FoF | Recorded | Proposed')
    for action in comparison.actions:
        text += f'\n{action.name} | {action.inside_potency:,.1f} | '
        text += (f'{action.recorded_potency:,.1f}' if recorded_best else
                 f'{action.recorded_potency:,.1f} | {action.proposed_potency:,.1f}')
    text += f'\nTotal | {comparison.inside_potency:,.1f} | '
    text += (f'{comparison.recorded_potency:,.1f}' if recorded_best else
             f'{comparison.recorded_potency:,.1f} | {comparison.proposed_potency:,.1f}')
    gain = comparison.proposed_potency - comparison.inside_potency
    if abs(gain) < .05:
        text += '\nThe proposed uses match the inside-FoF potency.'
    else:
        text += f"\nHolding {'gained' if gain > 0 else 'lost'} {abs(gain):,.1f} potency."
    for action in comparison.actions:
        text += (f'\n- {action.name}: {stamp(action.cast_seconds)}, {action.targets} '
                 + ('target' if action.targets == 1 else 'targets')
                 + (', Requiescat' if action.enhancement == 'Requiescat' else
                    ', unenhanced' if action.name != 'Blade of Honor' else '') + '.')
        recorded = next((c for c in window.held_cleaves if c.name == action.name
                         and abs(c.cast_seconds - action.cast_seconds) < .002), None)
        if recorded is not None and recorded.held_effects:
            text += ' Buffs: ' + ', '.join(recorded.held_effects) + '.'
    text += '\nOther recorded actions in the next burst are preserved.'
    return text


def package_tradeoff_notes(window, hit_context=()):
    if (window.actual_package_potency is None or window.best_package_potency is None
            or window.best_package_potency <= window.actual_package_potency):
        return {}
    return {col: (f"Recorded: {action.casts} "
                  f"{'cast' if action.casts == 1 else 'casts'}.\n"
                  f"Comparison: {action.expected} "
                  f"{'cast' if action.expected == 1 else 'casts'}.\n"
                  "See Completion for the package comparison.")
            for col, action in enumerate(window.actions)
            if action.expected is not None and action.package_casts > action.expected}


def package_completion_state(window):
    if window.attributed_followups:
        return "info"
    if window.held_cleaves and window.actual_package_potency is None:
        return "info"
    if window.comparison_notes:
        return "review"
    if (window.actual_package_potency is not None and window.best_package_potency is not None
            and window.actual_package_potency < window.best_package_potency):
        return "shortfall"
    return "info"


def package_completion_needs_note(window):
    return bool(window.hold_comparison or window.carried_casts or window.comparison_notes or (
        window.actual_package_potency is not None and window.best_package_potency is not None
        and round(window.best_package_potency - window.actual_package_potency, 1) > 0))


def package_completion_note(window):
    from .cli import _format_timestamp
    note = hold_comparison_note(window, _format_timestamp)
    if window.actual_package_potency is not None and window.best_package_potency is not None:
        note += ('\n' if note else '') + (f"Recorded / proposed potency: {window.actual_package_potency:,.1f} / "
                f"{window.best_package_potency:,.1f}.")
        if round(window.best_package_potency - window.actual_package_potency, 1) > 0:
            note += (f"\nEstimated gain: "
                     f"{window.best_package_potency - window.actual_package_potency:,.1f} base potency.")
            if not window.proposed_order:
                package = ', '.join(f"{a.expected} {a.name}" for a in window.actions
                                    if a.expected and a.name != 'Infuriate')
                note += f"\nSelected package: {package}."
        if window.periodic_actions:
            note += ('\nCircle of Scorn includes expected ticks until HP lock, untargetability or expiry.'
                     '\nTick timing is averaged at one tick per 3 seconds for both orders.')
    if window.alignment_notes:
        note += " Completion scores actions inside the window, not potion timing.\n"
        note += '\n'.join('- ' + text for text in window.alignment_notes)
    if window.comparison_notes:
        note += '\n' + '\n'.join(window.comparison_notes)
    if window.proposed_order:
        if any(name not in {a.name for a in window.actions} for name, _ in window.recorded_order):
            note += '\nOther abilities stay in roughly the same weave slots.'
        if any(t.projected for t in window.proposed_timings):
            note += '\nProposed hit times are estimates from this log.'

        def precise_time(seconds):
            sign = '-' if seconds < 0 else ''
            minutes, remaining = divmod(abs(seconds), 60)
            return f"{sign}{int(minutes):02d}m {remaining:06.3f}s"

        for label, order, timings in (("Recorded order", window.recorded_order, window.recorded_timings),
                                      ("Proposed order", window.proposed_order, window.proposed_timings)):
            timed = {(t.name, t.cast_seconds): t for t in timings}
            note += f"\n{label}:"
            for name, seconds in sorted((*order, *window.boundary_events), key=lambda row: row[1]):
                timing = timed.get((name, seconds))
                note += f"\n- {precise_time(seconds)} {name}"
                if any(c.name == name and abs(c.cast_seconds - seconds) < .002
                       for c in window.carried_casts):
                    note += ' (from the previous window)'
                elif label == 'Recorded order' and any(
                    c.name == name and abs(c.cast_seconds - seconds) < .002
                    for c in window.held_casts):
                    note += ' (Held)'
                elif label == 'Proposed order' and seconds >= window.end_seconds and (
                    any(c.name == name for c in window.held_casts)
                    or window.hold_comparison is not None
                    and any(a.name == name for a in window.hold_comparison.actions)):
                    note += ' (Hold)'
                if timing is not None:
                    if timing.hit_seconds:
                        hits = ', '.join(precise_time(t) for t in timing.hit_seconds)
                        note += f" | {hits} {'Estimated Hit' if timing.projected else 'Hit'}"
                    else:
                        note += ' | Estimated Hit (time unknown)' if timing.projected else ' | No landed hit'
    return note.strip()


def potion_boundary_notes(windows):
    return {(row, col): ('\n'.join('- ' + text for text in notes)
                         + '\n\nReview potion alignment; check downtime, targets and resources before moving it.')
            for row, window in enumerate(windows)
            for col, notes in ((1, window.before_window_notes), (2, window.after_window_notes))
            if notes}


def explain_packages(explanations, windows=()):
    explain_once("Cells show recorded casts / proposed casts.", explanations)
    explain_once("Completion compares recorded potency with the best feasible action order.", explanations)
    explain_once("Comparisons respect resources, cooldowns, GCDs, weaving, hit delays, deaths and downtime, preserving later uses.", explanations)
    if any(w.periodic_actions for w in windows):
        explain_once("Scorn includes expected ticks until expiry, HP lock or untargetability, averaging one tick every 3 seconds.", explanations)


def add_followup_tooltips(notes, windows, context, *, hit_table=False,
                         action_offset=None, start_column=None):
    notes = dict(notes)
    offset = (1 if hit_table else 3) if action_offset is None else action_offset
    start_col = (0 if hit_table else 1) if start_column is None else start_column
    for row, window in enumerate(windows):
        actions = [a for a in window.actions if not hit_table or a.name != "Infuriate"]
        for time, names, text in context:
            owners = {i for i, owner in enumerate(windows) for held in owner.held_casts
                      if abs(held.cast_seconds - time) < .002 and held.name in names}
            if (owners and row not in owners or not owners
                    and not window.start_seconds <= time < window.end_seconds):
                continue
            columns = ([start_col] if not names else
                       [col + offset for col, action in enumerate(actions)
                        if action.name in names])
            for col in columns:
                prior = notes.get((row, col), "")
                if text.strip().startswith("First hit blocked by the HP lock."):
                    notes[row, col] = (text.strip() + "\n" + prior).strip()
                else:
                    notes[row, col] = (prior + "\n" + text.strip()).strip()
    return notes


def print_burst_opportunities(windows, stamp, *, job="paladin", numbers=None, explanations=None,
                              hit_context=(), followup_context=()):
    explanations = set() if explanations is None else explanations
    if not windows:
        effect = "Fight or Flight" if job == "paladin" else "potion"
        emit_text(f"\n  Burst completion: unavailable (no recorded {effect} windows).")
        return
    labels = (("Imperator", "Goring", "Confiteor", "Faith", "Truth", "Valor", "Honor",
               "Scorn", "Expiacion", "Intervene") if job == "paladin" else
              ("IR spenders", "Infuriate", "NC", "Rend", "Ruination", "Wrath", "Upheaval", "Onslaught"))
    numbers = tuple(range(1, len(windows) + 1)) if numbers is None else numbers

    missing_hits = {
        (row, col): (
            f"{action.name}: {action.casts} completed "
            f"{'cast' if action.casts == 1 else 'casts'}, {action.hits} landed "
            f"{'hit' if action.hits == 1 else 'hits'}. "
        )
        for row, window in enumerate(windows)
        for col, action in enumerate(window.actions)
        if action.hits < action.package_casts and action.name != "Infuriate"
    }
    earned_notes = {
        (row, col): (f"Comparison: {action.expected} casts. " + package_action_notes(action)).strip()
        for row, window in enumerate(windows)
        for col, action in enumerate(window.actions)
        if action.expected is not None and action.package_casts < action.expected
    }
    tradeoff_notes = {(row, col): note for row, window in enumerate(windows)
                     for col, note in package_tradeoff_notes(window, hit_context).items()}
    resource_notes = {(row, col): package_action_notes(action)
                      for row, window in enumerate(windows)
                      for col, action in enumerate(window.actions)
                      if (action.name == "Infuriate" or action.review or action.excluded_casts) and (action.notes or action.excluded_casts)}
    cleave_states = {}
    for row, window in enumerate(windows):
        for held in window.held_casts:
            col = next((i for i, action in enumerate(window.actions) if action.name == held.name), None)
            if col is not None:
                resource_notes[row, col] = (f"Granted by this burst, used at {stamp(held.cast_seconds)}.\n"
                                           f"{held.hits} landed {'hit' if held.hits == 1 else 'hits'}.")
                cleave_states[row, col + 3] = 'info' if held.hits else 'missing-hit'
        for comparison in window.held_cleaves:
            col = next((i for i, action in enumerate(window.actions) if action.name == comparison.name), None)
            if col is not None:
                resource_notes[row, col] = ('Granted by this burst.\n' if window.held_casts else '') + held_cleave_note(window, comparison, stamp)
                group_gain = sum(c.held_potency - c.earlier_potency for c in window.held_cleaves)
                cleave_states[row, col + 3] = 'info' if group_gain >= 0 else 'shortfall'
    cast_notes = {}
    for key in tradeoff_notes.keys() | earned_notes.keys() | missing_hits.keys() | resource_notes.keys():
        cast_notes[key] = " ".join(dict.fromkeys(
            group[key] for group in (tradeoff_notes, earned_notes, missing_hits, resource_notes)
            if key in group))
    completion_notes = {
        (row, len(labels) + 3): (
            package_completion_note(window)
        )
        for row, window in enumerate(windows)
        if package_completion_needs_note(window)
    }
    completion_states = {(row, len(labels) + 3): package_completion_state(window)
        for row, window in enumerate(windows) if (row, len(labels) + 3) in completion_notes}
    boundary_notes = potion_boundary_notes(windows)
    for row, window in enumerate(windows):
        if window.alignment_notes:
            key = row, len(labels) + 3
            completion_notes[key] = package_completion_note(window)
            completion_states.setdefault(key, "review")
    emit_text("\n  Burst completion:" if job == "paladin" else "\n  Potion burst completion:")
    identity = ("Burst", "Buff start", "Buff end") if job == "paladin" else ("Potion", "Start", "End")
    table((*identity, *labels, "Completion"),
          [(str(i), stamp(w.start_seconds), stamp(w.end_seconds),
            *(str(a.casts) if a.name == "Infuriate" else
              f"{a.package_casts}/{a.expected if a.expected is not None else '?'}" for a in w.actions),
            burst_completion(w))
           for i, w in zip(numbers, windows)],
          cell_notes=add_followup_tooltips(
              {**{(row, col + 3): note for (row, col), note in cast_notes.items()},
               **completion_notes, **boundary_notes}, windows, followup_context),
          cell_states={**{(row, col + 3): "info" for row, window in enumerate(windows)
                          for col, _ in enumerate(window.actions)},
                       **{(row, col + 3): "missing-hit" for row, col in missing_hits},
                       **{(row, col + 3): "shortfall" for row, col in tradeoff_notes
                          if (row, col) not in missing_hits},
                       **{(row, col + 3): "shortfall" for row, col in earned_notes
                          if (row, col) not in missing_hits},
                       **{(row, col + 3): "review" for row, window in enumerate(windows)
                          for col, action in enumerate(window.actions) if action.review
                          and (row, col) not in missing_hits and (row, col) not in earned_notes},
                       **{(row, col + 3): "info" for row, window in enumerate(windows)
                          for col, action in enumerate(window.actions)
                          if (action.name == "Infuriate" or action.excluded_casts) and (action.notes or action.excluded_casts)
                          and action.hits >= action.package_casts
                          and (row, col) not in earned_notes},
                       **completion_states,
                       **cleave_states,
                       **dict.fromkeys(boundary_notes, "review")})
    explain_packages(explanations, windows)
    if any(w.held_cleaves for w in windows):
        explain_once("Hold comparisons include personal buffs and potions, excluding DH/Crit and other players' buffs.", explanations)
    if any(a.expected is None for w in windows for a in w.actions):
        explain_once("Expectations can be unknown when follow-ups were used on multiple targets outside the window.", explanations)
    if job == "warrior":
        emit_text("  Infuriate counts uses, not damage, and does not affect completion.")
    emit_text("\n  Landed hits and potency:")
    hit_labels = tuple(label for label in labels if label != "Infuriate")
    table((identity[0], *hit_labels, "Landed potency"),
          [(str(i), *(str(a.hits) for a in w.actions if a.name != "Infuriate"), f"{w.landed_potency:,.1f}")
           for i, w in zip(numbers, windows)],
          cell_notes=add_followup_tooltips(
              {(row, col + 1 - (job == "warrior" and col > 1)): note
               for (row, col), note in missing_hits.items()}, windows, followup_context, hit_table=True))
    emit_text("  Hits count actions granted by each burst, including held follow-ups and delayed hits. DoT ticks are excluded."
              if job == 'paladin' else
              "  Hits include later impacts from these casts, but exclude DoT ticks.")
    snapshot = "Fight or Flight" if job == "paladin" else "potion"
    emit_text("  Potency includes all landed damage with a Fight or Flight snapshot, including DoT ticks and auto-attacks."
              if job == 'paladin' else
              f"  Potency includes all landed damage and auto-attacks with a {snapshot} snapshot.")


def print_job_packages(groups: Iterable[tuple[str, Sequence[BurstWindow]]], stamp, *, explanations=None, job=None, hit_context=(),
                       action_order=(), followup_context=()):
    explanations = set() if explanations is None else explanations
    short_names: dict[str, str] = {full: short for short, full in ACTION_HEADERS.items()}
    for effect, windows in groups:
        if not windows:
            continue
        if action_order:
            order = {name: index for index, name in enumerate(action_order)}
            windows = tuple(replace(window, actions=tuple(sorted(
                window.actions, key=lambda action: order.get(action.name, len(order)))))
                for window in windows)
        emit_text(f"\n  {effect} burst completion:")
        labels = tuple(short_names.get(action.name, action.name) for action in windows[0].actions)
        notes = {}
        states = {}
        for row, window in enumerate(windows):
            for col, note in package_tradeoff_notes(window, hit_context).items():
                notes[row, col + 3] = note
                states[row, col + 3] = 'shortfall'
            if package_completion_needs_note(window):
                col = len(labels) + 3
                notes[row, col] = package_completion_note(window)
                states[row, col] = package_completion_state(window)
            if window.alignment_notes:
                notes[row, len(labels) + 3] = package_completion_note(window)
                states.setdefault((row, len(labels) + 3), 'review')
            for col, action in enumerate(window.actions, 3):
                if action.expected is not None and action.package_casts < action.expected:
                    notes[row, col] = f"Comparison: {action.expected} casts."
                    states[row, col] = 'shortfall'
                if action.notes or action.excluded_casts:
                    notes[row, col] = (notes.get((row, col), '') + ' ' + package_action_notes(action)).strip()
                    states.setdefault((row, col), 'review' if action.review else 'info')
                if action.hits < action.package_casts and 'non-damaging resource grant' not in action.notes:
                    notes[row, col] = (notes.get((row, col), '') + ' '
                                      + f"{action.casts} completed casts, {action.hits} landed hits.").strip()
                    states[row, col] = "missing-hit"
        boundaries = potion_boundary_notes(windows)
        notes.update(boundaries)
        states.update(dict.fromkeys(boundaries, 'review'))
        table(("Burst", "Start", "End", *labels, "Completion"),
              [(str(i), stamp(w.start_seconds), stamp(w.end_seconds),
                *(f"{a.package_casts}/{a.expected if a.expected is not None else '?'}" for a in w.actions),
                burst_completion(w)) for i, w in enumerate(windows, 1)],
              cell_notes=add_followup_tooltips(notes, windows, followup_context), cell_states=states)
        explain_packages(explanations, windows)
        if job in {"bard", "machinist", "dancer"}:
            explain_once("Gauge is based on recorded spends. Additional generation is not assumed.", explanations)


def print_cooldown_timing(rows):
    if not rows:
        return
    emit_text("\n  Cooldown timing:")
    table(("Action", "Ready while usable", "Longest delay"),
          [(r.name, f"{r.ready_seconds:.1f}s" if r.ready_seconds is not None else "n/a",
            f"{r.longest_delay_seconds:.1f}s" if r.longest_delay_seconds is not None else "n/a")
           for r in rows],
          cell_notes={(i, 0): "Confirmed time at full charges. Actual time may be longer."
                      for i, r in enumerate(rows) if r.minimum},
          cell_states={(i, 0): "info" for i, r in enumerate(rows) if r.minimum})
    emit_text("  Timing starts at first use and counts usable time while alive. Delays may align with buffs.")


def print_burst_alignment(alignments, stamp):
    for alignment in alignments:
        emit_text()
        if not alignment.evidence_available:
            emit_text(f"  {alignment.name} alignment: unavailable (no recorded buff windows).")
            continue
        total = alignment.inside_potency + alignment.outside_potency
        coverage = f"{alignment.inside_potency / total:.1%}" if total else "n/a"
        label = (f"Landed potency inside {alignment.name}" if alignment.kind != "guaranteed"
                 else f"Landed potency enhanced by {alignment.name}")
        emit_text(f"  {label}: {alignment.inside_potency:,.1f} / {total:,.1f} ({coverage})")
        emit_text(fill("Scope: " + ", ".join(alignment.scope) + ".", width=100,
                   initial_indent="  ", subsequent_indent="         "))
        table(("Burst", "Buff start", "Buff end", "Inside", "Outside", "Coverage"),
              [(str(i), stamp(w.start_seconds), stamp(w.end_seconds),
                f"{w.inside_potency:,.1f}", f"{w.outside_potency:,.1f}",
                f"{w.inside_potency / (w.inside_potency + w.outside_potency):.1%}"
                if w.inside_potency + w.outside_potency else "n/a")
               for i, w in enumerate(alignment.windows, 1)])
        if alignment.outside:
            heading = (f"Actions outside {alignment.name}" if alignment.kind != "guaranteed"
                       else f"Actions without {alignment.name}")
            emit_text(f"\n  {heading}:")
            gain = "Potential buff gain" if alignment.kind == "damage" else "Expected hit-bonus gain"
            table(("Action", "Uses", "Potency", gain),
                  [(r.action, str(r.uses), f"{r.potency:,.1f}", f"{r.potential_gain:,.1f}")
                   for r in alignment.outside])
        if alignment.kind == "damage":
            emit_text(f"  Potency excludes {alignment.name}. Includes regular uses between buff windows.")
        else:
            emit_text("  Hit-bonus gains estimate damage using assumed gear and baseline DH/Crit rates.")
            emit_text("  These estimates exclude other players' rate buffs and do not change potency or PPS.")
        if alignment.kind == "guaranteed":
            emit_text("  Finite charges and regular uses between windows limit achievable gains.")
        if len(alignments) > 1:
            emit_text("  Overlapping buff estimates are separate and should not be added.")
        emit_text("  Potential gains are not confirmed losses.")


def print_combo_diagnostics(combos, stamp, *, heading=True):
    if combos is None:
        return
    if heading:
        emit_text("\nCombos:")
    if combos.losses:
        table(("Action", "Uncomboed hits", "Base potency lost"),
              [(r.name, str(r.hits), f"{r.potency_lost:,.1f}")
               for r in sorted(combos.losses, key=lambda r: (-r.potency_lost, r.name))])
        emit_text("  Base potency lost excludes overkill, buffs and penalties.")
    else:
        emit_text("  No recorded combo losses.")
    if combos.unconfirmed_hits:
        n = combos.unconfirmed_hits
        emit_text(f"  Unconfirmed combo evidence: {n} landed " + ("hit" if n == 1 else "hits"))
        emit_text("  Unknown combo hits use a potency range from uncomboed to comboed.")
    grouped = {}
    for row in sorted(combos.inferred, key=lambda r: r.seconds):
        if row.comboed:
            continue
        key = (row.packet if row.packet is not None else row.seconds, row.name)
        if key not in grouped:
            grouped[key] = row, 0, 0.0
        first, hits, loss = grouped[key]
        grouped[key] = first, hits + 1, loss + row.potency_lost
    for row, hits, loss in grouped.values():
        previous = row.previous_gcd or "previous GCD unavailable"
        evidence = f"{hits} landed hits; " if hits > 1 else ""
        emit_text(f"  {stamp(row.seconds)} {previous} -> {row.name}: "
              + f"{loss:,.1f} estimated base potency lost "
              + f"({evidence}uncomboed inferred from normalized damage; combo field unavailable)")


def print_follow_up_context(rows, stamp):
    if not rows:
        return
    emit_text("\n  Follow-up context:")
    for row in rows:
        label = "Cast" if row.outcome == "cast, no hit" else "Sequence"
        outcome = "casts, no hits" if row.outcome == "cast, no hit" and len(row.actions) > 1 else row.outcome
        detail = f"{', '.join(row.actions)}" + (f" {outcome}" if outcome != "incomplete" else "")
        emit_text(f"    {label} {stamp(row.seconds)}: {detail} - {row.reason}")

def reported_coverage_gaps(effect: Coverage) -> tuple[tuple[float, float], ...]:
    """Suppress small DoT warning gaps without changing calculated coverage."""
    return tuple(
        (begin, end) for begin, end in effect.avoidable_gaps
        if effect.name not in DOT_NAMES or end - begin > 1.0 + 1e-9
    )


def table(
    labels: tuple[str, ...],
    rows: list[tuple[str, ...]],
    indent: str = "  ",
    notes: list[str] | None = None,
    blank_before: bool = False,
    column_widths: list[int] | None = None,
    cell_notes: dict[tuple[int, int], str] | None = None,
    cell_states: dict[tuple[int, int], str] | None = None,
) -> None:
    if not rows:
        return
    if emit_table(labels, rows, notes, indent, cell_notes, cell_states):
        return
    widths = [max(len(label), *(len(row[i]) for row in rows)) for i, label in enumerate(labels)]
    if column_widths is not None:
        widths = [max(width, shared) for width, shared in zip(widths, column_widths)]

    def line(row):
        return indent + "  ".join(
            f"{value:<{width}}" if i == 0 else f"{value:>{width}}"
            for i, (value, width) in enumerate(zip(row, widths))
        )

    if blank_before:
        emit_text()
    emit_text(line(labels))
    for i, row in enumerate(rows):
        emit_text(line(row))
        if notes and notes[i]:
            for note_line in notes[i].splitlines():
                emit_text(indent + "  " + note_line)


def wildfire_note(window: MchWildfireSummary) -> str:
    if window.landed_weaponskills >= 6:
        return ""
    if not window.contributing_actions:
        return "WF -> no contributing GCDs"
    if (window.cast_seconds is None
            or len(window.contributing_times) != len(window.contributing_actions)):
        return "GCDs: " + " -> ".join("BS" if name == "Blazing Shot" else name for name in window.contributing_actions)
    chain = "WF"
    previous = window.cast_seconds
    for index, (time, action) in enumerate(zip(window.contributing_times, window.contributing_actions)):
        gap = time - previous
        action = "BS" if action == "Blazing Shot" else action
        if index == 0 and gap < 0:
            chain += f" -> {action} (cast {-gap:.2f}s before WF)"
        else:
            chain += f" -> {gap:.2f}s -> {action}"
        previous = time
    elapsed = previous - window.cast_seconds
    total = (f"Time to last GCD: {elapsed:.2f}s" if elapsed >= 0
             else f"Last GCD cast {-elapsed:.2f}s before WF")
    if window.ended_seconds is not None:
        remaining = window.ended_seconds - previous
        if remaining >= 0:
            ending = "WF detonates" if window.detonated_early else "WF expires"
            if window.detonated_seconds is None:
                ending = "WF ends"
            chain += f" -> {remaining:.2f}s -> {ending}"
    return chain + "\n" + total


def loss_details(effect, include_remaining=True):
    return [
        f"{value} {label}"
        for label, value in (
            ("expired", effect.expired),
            ("overwritten", effect.overwritten),
            ("lost on death", getattr(effect, "death_lost", 0)),
            ("remaining", effect.remaining if include_remaining else 0),
        )
        if value
    ]


def ready_line(effect):
    if not getattr(effect, "evidence_available", True):
        return f"{effect.name}: {effect.observed_uses} uses (grant evidence unavailable)"
    return " | ".join(
        [f"{effect.name}: {effect.uses}/{effect.grants} grants used", *loss_details(effect)]
    )


def ready_loss_findings(effects):
    """Use the same loss wording for every job's tracked ready effects."""
    return [
        f"{effect.name}: " + " | ".join(
            f"{value} {label}" for label, value in (
                ("expired", effect.expired),
                ("overwritten", effect.overwritten),
                ("lost on death", getattr(effect, "death_lost", 0)),
            ) if value
        )
        for effect in effects
        if effect.expired or effect.overwritten or getattr(effect, "death_lost", 0)
    ]


def confirmed_ghosts(result: AnalysisResult) -> list[tuple[float, str, str, str]]:
    low = {(time, name) for name, events in result.ghosted_target_low_hp for time, _ in events}
    targets = {
        (time, name): target for name, events in result.ghosted_targets for time, target in events
    }
    return sorted(
        (time, name, targets.get((time, name), ""), reason)
        for name, events in result.ghosted_ending_times
        for time, reason in events
        if (time, name) not in low
        and (
            "target became untargetable" in reason
            or reason.startswith(("target defeated", "target died"))
        )
    )


def missing_hit_context(result: AnalysisResult) -> list[tuple[float, str, str, str]]:
    """Reuse recorded ghost, HP-lock and unconfirmed evidence in burst notes."""
    confirmed = confirmed_ghosts(result)
    seen = {(time, name) for time, name, _, _ in confirmed}
    endings = {(time, name): reason for name, events in result.ghosted_ending_times
               for time, reason in events}
    low = {(time, name): hp for name, events in result.ghosted_target_low_hp for time, hp in events}
    targets = {(time, name): target for name, events in result.ghosted_targets
               for time, target in events}
    return sorted(confirmed + [
        (time, name, targets.get((time, name), ""),
         f"target at {low[time, name]} HP" if (time, name) in low
         else endings.get((time, name), "reason unconfirmed"))
        for name, times in result.ghosted_times for time in times if (time, name) not in seen
    ])


def pld_followup_context(bursts, windows, result, stamp):
    recorded = [entry for entry in missing_hit_context(result) if any(
        window.start_seconds <= entry[0] < window.end_seconds
        and any(action.name == entry[1] and action.hits < action.casts
                for action in window.actions) for window in windows
    )]
    first_hp_locks = set()
    for window in windows:
        seen_targets = set()
        for time, name, target, reason in recorded:
            if (reason == "phase HP lock" and target not in seen_targets
                    and window.start_seconds <= time < window.end_seconds):
                first_hp_locks.add((time, name, target))
                seen_targets.add(target)
    entries = []
    for time, name, target, reason in recorded:
        action = f"    {stamp(time)} {name}" + (f" on {target}" if target else "")
        if (time, name, target) in first_hp_locks:
            text = "    First hit blocked by the HP lock.\n" + action
        else:
            text = action + f" ({reason})"
        entries.append((time, (name,), text))
    for index, burst in enumerate(bursts):
        end = bursts[index + 1].seconds if index + 1 < len(bursts) else result.duration_seconds
        explained = {name for time, name, _, _ in recorded if burst.seconds <= time < end}
        for issue in burst.issues:
            actions = tuple(name for name in issue.actions
                            if issue.kind != "no_hit" or name not in explained)
            if not actions:
                continue
            outcome = (("cast, no hit" if len(actions) == 1 else "casts, no hits")
                       if issue.kind == "no_hit" else "missing")
            reason = {
                "death": "player died during sequence",
                "downtime": "boss downtime during sequence" if issue.kind == "missing_cast" else "boss downtime",
                "fight_end": "fight ended during sequence",
                "fight ending": "fight ended before hit landed",
                "expiry": f"{issue.effect} expired",
                "prepull": "sequence began before saved interval",
                "unconfirmed": "reason unconfirmed",
            }.get(issue.reason, issue.reason)
            entries.append((burst.seconds, actions,
                            f"    Burst {stamp(burst.seconds)}: {', '.join(actions)} {outcome} - {reason}"))
        action_order = {action.name: index for index, action in enumerate(burst.follow_ups)}
        grouped_notes = sorted(burst.notes, key=lambda note: action_order.get(
            note.partition(':')[0], len(action_order)))
        entries.extend((burst.seconds, (), f"    Burst {stamp(burst.seconds)}: {note}")
                       for note in grouped_notes)
    return tuple(sorted(entries, key=lambda row: row[0]))


def print_pld_followup_context(bursts, windows, result, stamp):
    entries = pld_followup_context(bursts, windows, result, stamp)
    if entries:
        emit_text("\n  Follow-up context:")
        for _, _, line in entries:
            emit_text(line)


def war_followup_context(result: AnalysisResult, stamp):
    from .analysis.war.bursts import POTION_ACTIONS

    actions_with_damage = {name for label, consumers in POTION_ACTIONS
                           if label != "Infuriate" for name in consumers}
    recorded = [row for row in missing_hit_context(result) if row[1] in actions_with_damage]
    explained = {(name, time) for time, name, _, _ in recorded}
    labels: dict[str, str] = {name: label for label, consumers in POTION_ACTIONS for name in consumers}
    entries: list[tuple[float, tuple[str, ...], str]] = [(time, (labels[name],), f"    {stamp(time)} {name}" + (f" on {target}" if target else "")
                + f" ({reason})") for time, name, target, reason in recorded]
    for row in result.follow_up_context:
        actions = tuple(name for name in row.actions
                        if row.outcome != "cast, no hit" or (name, row.seconds) not in explained)
        if actions:
            detail = ", ".join(actions)
            if row.outcome != "incomplete":
                detail += " " + row.outcome
            mapped = tuple(dict.fromkeys(
                "IR spenders" if name.startswith("Inner Release spenders") else
                labels.get(name, name) for name in actions))
            entries.append((row.seconds, mapped,
                            f"    {stamp(row.seconds)} {detail} - {row.reason}"))
    return tuple(sorted(entries, key=lambda row: row[0]))


def print_war_followup_context(result, stamp):
    entries = war_followup_context(result, stamp)
    if entries:
        emit_text("\n  Follow-up context:")
        for _, _, line in entries:
            emit_text(line)


def issue_notes(result: AnalysisResult) -> str:
    deaths = sum(w.name == "Dead" for w in result.status_windows)
    dd = sum(w.name == "Damage Down" for w in result.status_windows)
    ghosts = len(confirmed_ghosts(result))
    return (
        " ".join(
            f"{label}x{count}"
            for label, count in (("KO", deaths), ("DD", dd), ("G", ghosts))
            if count
        )
        or "-"
    )


def tomahawk_summary(war):
    uses = sum(1 + len(chain.gaps) for chain in war.tomahawks)
    count = len(war.tomahawks)
    return f"Tomahawk: {uses} uses in {count} " + ("chain" if count == 1 else "chains")


def print_analysis(
    result: AnalysisResult, *, directory: Path | None, anonymous: bool, rank: int | None,
    tooltip_context: bool = False,
) -> None:
    from . import cli

    duration = cli._format_duration
    stamp = cli._format_timestamp
    potency = cli._format_potency
    execution = result.execution
    job = execution.job if execution else (cli._source_job(directory) if directory else "")
    counts = (
        dict(execution.cast_counts) if execution else {a.name: a.uses or 0 for a in result.actions}
    )
    cooldowns = {c.name: c for c in execution.cooldowns} if execution else {}
    partition, bracket = cli._fight_provenance(directory) if directory else ("n/a", "n/a")
    targetable = (
        duration(result.targetable_seconds) if result.targetable_seconds is not None else "n/a"
    )
    if "estimated" in result.targetable_time_source:
        targetable = "~" + targetable
    food = result.food.name if result.food else "None"
    if result.food and not result.food.recorded:
        food += " (unverified)"
    gear = f"{result.gear_name} ({result.gear_source})" if result.gear_name else "custom profile"
    patch_source = (result.patch_source or "").replace(
        "latest configured patch (date unavailable)", "latest configured patch, date unavailable"
    )
    emit_text()
    emit_text(
        f"Player: {cli._display_player_name(result.source_name, anonymous=anonymous)}"
        + (f" | Rank: {rank}" if rank is not None else "")
    )
    emit_text(
        f"Fight: {cli._format_fight(result)} | Duration: {duration(result.duration_seconds)}"
        + (" (wipe)" if result.kill is False else "")
        + f" | Targetable: {targetable}"
    )
    emit_text(
        f"Date: {cli._fight_date(directory, full_year=True) if directory else 'n/a'} (UTC) | Patch: {result.played_patch or bracket}"
        + (f" ({patch_source})" if patch_source and patch_source != "fight date" else "")
    )
    emit_text(f"Gear: {gear} | Food: {food}")
    metrics = []
    if result.encounter_id in {4549, 4551}:
        metrics.append(f"DPS: {result.dps:,.1f}" if result.dps is not None else "DPS: n/a")
    elif (
        job in {"paladin", "warrior", "machinist"}
        and result.rdps is not None
        and result.ndps is not None
        and round(result.rdps, 1) == round(result.ndps, 1)
    ):
        metrics.append(f"rDPS/nDPS: {result.rdps:,.1f}")
    else:
        metrics.extend(
            f"{label}: {value:,.1f}" if value is not None else f"{label}: n/a"
            for label, value in (("rDPS", result.rdps), ("nDPS", result.ndps))
        )
    emit_text(
        f"\nLanded potency: {potency(result.potency_min, result.potency_max)} | PPS: {cli._format_pps(result.pps_min, result.pps_max)} | "
        + " | ".join(metrics)
    )

    findings = []
    deaths = [w for w in result.status_windows if w.name == "Dead"]
    if deaths:
        findings.append(f"Deaths: {len(deaths)}")
    for p in result.damage_penalties:
        windows = [w for w in result.status_windows if w.name == p.name]
        total = sum(w.end_seconds - w.start_seconds for w in windows)
        findings.append(
            f"{p.name}: {total:.1f}s" if windows else f"{p.name}: {p.affected_hits} affected hits"
        )
    if result.war:
        w = result.war
        if w.tempest_missing:
            findings.append(
                f"Surging Tempest: {len(w.tempest_missing)} avoidable unbuffed "
                + ("attack" if len(w.tempest_missing) == 1 else "attacks")
            )
        if w.unused_expired_charges:
            findings.append(
                f"Inner Release: {w.unused_expired_charges} expired"
            )
        findings.extend(ready_loss_findings(w.ready))
        if w.tomahawks:
            findings.append(tomahawk_summary(w))
    if result.combos and result.combos.losses:
        hits = sum(c.hits for c in result.combos.losses)
        findings.append(f"Combos: {hits} uncomboed " + ("hit" if hits == 1 else "hits"))
    if result.pld:
        combos = result.pld.combos
        if combos is not None and combos.losses:
            hits = sum(c.hits for c in combos.losses)
            findings.append(f"Combos: {hits} uncomboed " + ("hit" if hits == 1 else "hits")
                            + f", {sum(c.potency_lost for c in combos.losses):,.1f} base potency lost")
        findings.extend(ready_loss_findings(result.pld.ready))
        if result.pld.ranged:
            count = len(result.pld.ranged)
            findings.append(f"Melee downtime: {count} ranged " + ("chain" if count == 1 else "chains"))
    if execution:
        for c in execution.coverage:
            gaps = reported_coverage_gaps(c)  # Opening setup remains in actual coverage.
            if gaps:
                findings.append(f"{c.name}: {sum(b - a for a, b in gaps):.1f}s targetable gaps")
        findings.extend(ready_loss_findings(execution.ready))
        for time in execution.repertoire_losses:
            findings.append(
                f"Repertoire: at least 1 unused stack at {stamp(time)} (Empyreal Arrow confirmed)"
            )
    incomplete_wildfires = sum(w.landed_weaponskills < 6 for w in result.mch_wildfires)
    if incomplete_wildfires:
        findings.append(
            f"Wildfire: {incomplete_wildfires} "
            + ("use" if incomplete_wildfires == 1 else "uses")
            + " with fewer than 6 GCDs"
        )
    for d in result.pet_deployments:
        if d.mch_missing_finishers:
            findings.append(
                f"Queen: missing {' and '.join(d.mch_missing_finishers)} at {stamp(d.timestamp_seconds)}"
            )
    proc = result.dnc_procs
    if proc:
        findings.extend(ready_loss_findings(proc.ready_procs))
    ghosts = confirmed_ghosts(result)
    if ghosts:
        findings.append(
            f"Confirmed ghosted hits: {len(ghosts)}"
        )
    if result.reduced_damage_hits:
        findings.append(
            f"Reduced-damage hits: {len(result.reduced_damage_hits)}"
        )
    if proc:
        findings.append(
            f"Feather luck score: at least {proc.combined_feather_luck_min:.1f}/100"
            if proc.combined_feather_luck_min is not None
            else "Feather luck score: unavailable (insufficient or inconsistent resource evidence)"
        )
    if result.unmatched:
        findings.append("Unmatched damage present: potency is incomplete")
    emit_text("\nExecution summary:")
    for line in findings or ["No confirmed issues in this log."]:
        emit_text("  " + line)
    if result.pld and result.pld.combos:
        inferred_losses = [c for c in result.pld.combos.inferred if not c.comboed]
        if inferred_losses:
            hits = len(inferred_losses)
            emit_text(f"  Inferred combo losses: {hits} uncomboed "
                  + ("hit" if hits == 1 else "hits"))
    if result.combos:
        hits = sum(not c.comboed for c in result.combos.inferred)
        if hits:
            emit_text(f"  Inferred combo losses: {hits} uncomboed " + ("hit" if hits == 1 else "hits"))
    opportunities = [c for c in cooldowns.values()
                     if c.possible is not None and c.uses < c.possible]
    if opportunities:
        emit_text("  Cooldown opportunities:")
        for c in opportunities:
            detail = " (recorded Blazing Shots)" if "recorded Blazing Shots" in c.basis else ""
            emit_text(f"    {c.name}: {c.uses}/{c.possible} uses{detail}")

    emit_text("\nDeaths and damage penalties:")
    death_rows = []
    for i, w in enumerate(deaths, 1):
        inferred = w.end_reason.startswith("revived by next cast")
        remaining = w.end_reason == "fight ended"
        evidence = ("Next cast; wipe reset inferred" if "dungeon wipe reset" in w.end_reason
                    and inferred else "Next cast" if inferred else "Dead at fight end" if remaining else
                    "Recorded revival" if w.end_reason == "resurrected" else
                    w.end_reason.removeprefix("revived: "))
        death_rows.append((str(i), stamp(w.start_seconds),
                           "-" if remaining else stamp(w.end_seconds),
                           ("<= " if inferred else "")
                           + f"{w.end_seconds - w.start_seconds:.1f}s", evidence))
    table(("Death", "Died", "Alive by", "Time dead", "Revival evidence"), death_rows)
    if any(w.end_reason.startswith("revived by next cast") for w in deaths):
        emit_text("  Without a revival event, time dead runs to the next cast and may be overstated.")
    if any(w.end_reason == "fight ended" for w in deaths):
        emit_text("  Without a revival event or later cast, time dead runs to fight end.")
    if any("dungeon wipe reset" in w.end_reason for w in deaths):
        emit_text("  Reviving without Transcendent, Weakness or Brink of Death suggests a dungeon wipe reset.")
    rows = []
    penalty_totals = []
    penalty_notes = []
    for p in result.damage_penalties:
        windows = [w for w in result.status_windows if w.name == p.name]
        loss = (
            potency(p.lost_potency_min, p.lost_potency_max)
            if p.lost_potency_min is not None and p.lost_potency_max is not None
            else "n/a"
        )
        if windows:
            for w in windows:
                window_hits = [
                    (low, high) for time, low, high in p.hit_losses
                    if w.start_seconds <= time < w.end_seconds
                ]
                window_count = str(len(window_hits)) if p.hit_losses else (
                    str(p.affected_hits) if len(windows) == 1 else "n/a"
                )
                window_loss = potency(
                    sum(low for low, _ in window_hits), sum(high for _, high in window_hits)
                ) if p.hit_losses else (loss if len(windows) == 1 else "n/a")
                rows.append(
                    (
                        p.name,
                        stamp(w.start_seconds),
                        stamp(w.end_seconds),
                        f"{w.end_seconds - w.start_seconds:.1f}s",
                        window_count,
                        window_loss,
                        "removed early" if w.end_reason == "removed" else w.end_reason,
                    )
                )
                refresh_times = tuple(dict.fromkeys(
                    stamp(t) for t in w.refresh_seconds if stamp(t) != stamp(w.start_seconds)
                ))
                penalty_notes.append(
                    "Refreshed: " + ", ".join(refresh_times) if refresh_times else ""
                )
            duration = sum(w.end_seconds - w.start_seconds for w in windows)
            reduction = (
                f"Main stat: -{p.main_stat_reduction}%" if p.main_stat_reduction is not None
                else f"Damage: -{(1 - p.multiplier) * 100:.0f}%" if p.multiplier is not None
                else "Penalty: unknown"
            )
            penalty_totals.append(
                f"  {p.name} total: {duration:.1f}s | {reduction} | "
                f"Hits: {p.affected_hits} | Potency lost: {loss}"
            )
        else:
            rows.append(
                (
                    p.name,
                    stamp(p.first_observed_seconds),
                    stamp(p.last_observed_seconds),
                    "unknown",
                    str(p.affected_hits),
                    loss,
                    "observed hits only",
                )
            )
            penalty_notes.append("")
    table(
        ("Effect", "Start", "End", "Duration", "Hits", "Potency lost", "End"),
        rows,
        notes=None if tooltip_context else penalty_notes,
        cell_notes={(row, 3): note + ". Refreshes are included in this effect's duration."
                    for row, note in enumerate(penalty_notes) if note}
                   if tooltip_context else None,
        cell_states={(row, 3): "info" for row, note in enumerate(penalty_notes) if note}
                    if tooltip_context else None,
        blank_before=bool(deaths),
    )
    for line in penalty_totals:
        emit_text(line)
    if not deaths and not rows:
        emit_text("  No deaths or recorded damage downs.")
    elif rows:
        emit_text("  Potency lost covers landed attacks only. Attacks missed while dead are not estimated.")

    def uses(name):
        c = cooldowns.get(name)
        if c:
            return f"{c.uses}/{c.possible}" if c.possible is not None else str(c.uses)
        return str(counts.get(name, 0))

    def coverage_rows(names):
        effects = [c for c in execution.coverage if c.name in names] if execution else []
        detailed = any(c.applications or c.refreshes for c in effects)
        rows = []
        for c in effects:
            uptime = (
                f"{c.covered_seconds / c.targetable_seconds:.2%}" if c.targetable_seconds else "n/a"
            )
            rows.append(
                (c.name, uptime, f"{c.targetable_seconds - c.covered_seconds:.1f}s")
                + ((str(c.applications), str(c.refreshes)) if detailed else ())
            )
        labels = ("Effect", "Uptime", "Missing time")
        table(labels + (("Applications", "Refreshes") if detailed else ()), rows)
        for c in effects:
            for a, b in reported_coverage_gaps(c):
                emit_text(f"  {stamp(a)} - {stamp(b)} {c.name} ({b - a:.1f}s targetable)")

    def ready_lines(selected, indent="  "):
        for r in execution.ready if execution else ():
            if r.name in selected:
                emit_text(indent + ready_line(r))
                for time, reason in r.losses:
                    emit_text(f"{indent}  {stamp(time)}: {reason}")

    def coverage_line(name, label=None, indent="  "):
        c = next((c for c in execution.coverage if c.name == name), None) if execution else None
        if c:
            uptime = (
                f"{c.covered_seconds / c.targetable_seconds:.2%}" if c.targetable_seconds else "n/a"
            )
            emit_text(
                f"{indent}{label or 'Uptime'}: {uptime} | Missing time: {c.targetable_seconds - c.covered_seconds:.1f}s"
            )
            for a, b in reported_coverage_gaps(c):
                emit_text(f"{indent}  {stamp(a)} - {stamp(b)}: {b - a:.1f}s targetable gap")

    has_job_sections = bool(result.pld or result.war or job in {"bard", "machinist", "dancer"}
                            or result.brd_songs or result.brd_potency_estimates
                            or result.mch_wildfires or result.pet_deployments
                            or result.dnc_finishes or proc)

    def job_cooldowns():
        explanations = set()
        if has_job_sections:
            emit_text("\nCooldowns and burst windows:")
        if result.pld:
            p = result.pld
            for name in ("Fight or Flight", "Imperator", "Requiescat", "Circle of Scorn", "Expiacion", "Intervene"):
                if name != "Requiescat" or counts.get(name):
                    cooldown = cooldowns.get(name)
                    value = cooldown.uses if cooldown else counts.get(name, 0)
                    note = " (including pre-pull)" if cooldown and cooldown.pre_pull_uses else ""
                    emit_text(f"  {name}: {uses(name)} "
                              + ("use" if value == 1 else "uses") + note)
            if p.cooldown_timing:
                print_cooldown_timing(p.cooldown_timing)
            context_windows = (*p.burst_opportunities,
                               *(window for _, windows in result.burst_packages for window in windows))
            context = pld_followup_context(p.bursts, context_windows, result, stamp)
            print_burst_opportunities(p.burst_opportunities, stamp, explanations=explanations,
                                     hit_context=missing_hit_context(result), followup_context=context)
            if not tooltip_context:
                print_pld_followup_context(p.bursts, p.burst_opportunities, result, stamp)
            print_job_packages(result.burst_packages, stamp, explanations=explanations, job=job,
                               hit_context=missing_hit_context(result), action_order=PLD_POTION_ACTIONS,
                               followup_context=context)
            emit_text("\n  Spell casts:")
            enhancement_order = {"Divine Might": 0, "Requiescat": 1, "None": 2}
            spell_counts = sorted(p.spell_counts, key=lambda row: (
                row[0], enhancement_order.get(row[1], 3), row[2],
            ))
            table(("Spell", "Enhancement", "Cast evidence", "Casts"),
                  [(name, effect, "hard-cast" if kind == "hard cast" else kind, str(n))
                   for name, effect, kind, n in spell_counts])
        if result.war:
            w = result.war
            context = war_followup_context(result, stamp)
            emit_text(
                f"  Inner Release: {w.inner_release_uses}"
                + (
                    f"/{cooldowns['Inner Release'].possible}"
                    if "Inner Release" in cooldowns and cooldowns["Inner Release"].possible is not None
                    else ""
                )
                + " uses"
                + (" (including pre-pull)" if any(
                    b.seconds is None or b.seconds < 0 for b in w.bursts
                ) else "")
            )
            emit_text(
                f"  IR spenders: {w.guaranteed_spenders}/{3 * w.inner_release_uses} uses"
            )
            for r in w.ready:
                if r.name == "Nascent Chaos":
                    continue
                emit_text("  " + ready_line(r))
                for time, reason in (() if tooltip_context else r.losses):
                    emit_text(f"    {stamp(time)}: {reason}")
            emit_text(f"  Infuriate: {w.infuriate_uses} uses")
            for r in w.ready:
                if r.name == "Nascent Chaos":
                    emit_text("  " + ready_line(r))
                    for time, reason in (() if tooltip_context else r.losses):
                        emit_text(f"    {stamp(time)}: {reason}")
            for name in ("Upheaval/Orogeny", "Onslaught"):
                if name in cooldowns:
                    emit_text(f"  {name}: {uses(name)} "
                          + ("use" if cooldowns[name].uses == 1 else "uses"))
            print_cooldown_timing(result.cooldown_timing)
            if w.ir_opportunities:
                emit_text("\n  Inner Release sequences:")
                rows = []
                notes = {}
                states = {}
                for index, window in enumerate(w.ir_opportunities):
                    tradeoffs = package_tradeoff_notes(window, missing_hit_context(result))
                    for col, note in tradeoffs.items():
                        notes[index, col + 2] = note
                        states[index, col + 2] = "shortfall"
                    completion = burst_completion(window)
                    begin = ("Pre-pull" if w.bursts[index].seconds is None
                             else stamp(window.start_seconds))
                    rows.append((str(index + 1), begin,
                                 *(f"{a.package_casts}/{a.expected if a.expected is not None else '?'}"
                                   for a in window.actions), completion))
                    if package_completion_needs_note(window):
                        notes[index, 6] = package_completion_note(window)
                        states[index, 6] = package_completion_state(window)
                    for column, action in enumerate(window.actions, 2):
                        states.setdefault((index, column), "info")
                        if (action.expected is not None and action.package_casts < action.expected
                                and (index, 6) in notes):
                            notes[index, column] = f"Comparison: {action.expected} casts."
                            states[index, column] = "shortfall"
                        if (action.notes or action.excluded_casts) and (action.excluded_casts or (
                                action.expected is not None and action.package_casts < action.expected)):
                            notes[index, column] = (notes.get((index, column), "") + " "
                                                    + package_action_notes(action)).strip()
                            states[index, column] = ("info" if action.excluded_casts
                                                      and action.hits >= action.package_casts else "shortfall")
                        if action.hits < action.package_casts:
                            notes[index, column] = (notes.get((index, column), "") + " "
                                                    + f"{action.name}: {action.casts} completed casts, "
                                                    f"{action.hits} landed hits.").strip()
                            states[index, column] = "missing-hit"
                table(("Burst", "Start", "IR spenders", "Rend", "Ruination", "Wrath", "Completion"),
                      rows, cell_notes=add_followup_tooltips(
                          notes, w.ir_opportunities, context, action_offset=2), cell_states=states)
                explain_packages(explanations)
                emit_text("  IR spenders unlock follow-ups. Later follow-ups stay with their sequence.")
                if any(b.seconds is None for b in w.bursts):
                    emit_text("  Pre-pull uses are confirmed from opening buffs, IR-enhanced hits and charge consumption.")
                    emit_text("  Missing grant times leave unsupported expectations as ?.")
            potion_numbers = tuple(i for i, burst in enumerate(w.potion_bursts, 1)
                                   if burst.start_seconds is not None and burst.end_seconds is not None)
            print_burst_opportunities(w.potion_opportunities, stamp, job="warrior", numbers=potion_numbers,
                                      explanations=explanations, followup_context=context,
                                      hit_context=missing_hit_context(result))
            if len(w.potion_opportunities) < len(w.potion_bursts):
                emit_text("\n  Unconfirmed potion windows:")
                table(("Potion", "IR spenders", "Infuriate", "NC", "Rend", "Ruination", "Wrath",
                       "Upheaval", "Onslaught"),
                      [(str(i), *(str(count) for _, count in burst.casts))
                       for i, burst in enumerate(w.potion_bursts, 1)
                       if burst.start_seconds is None or burst.end_seconds is None])
                emit_text("  Counts use recorded potted-hit packets. Unknown boundaries are excluded from completion.")
            if not tooltip_context:
                print_war_followup_context(result, stamp)
        if job == "bard" or result.brd_songs or result.brd_potency_estimates:
            for name in ("Raging Strikes", "Battle Voice"):
                cooldown = cooldowns.get(name)
                note = " (including pre-pull)" if cooldown and cooldown.pre_pull_uses else ""
                emit_text(f"  {name}: {uses(name)} uses{note}")
            print_cooldown_timing(result.cooldown_timing)
            if not result.burst_packages:
                print_burst_alignment(result.burst_alignment, stamp)
            emit_text("\n  Radiant Finale and Encore:")
            emit_text(
                f"  Radiant Finale: {uses('Radiant Finale')} uses | Radiant Encore: {counts.get('Radiant Encore', 0)} uses"
            )
            table(
                ("Finale", "Codas", "Damage bonus", "Encore hits", "Encore potency"),
                [
                    (
                        stamp(f.timestamp_seconds),
                        str(f.coda),
                        f"{2 * f.coda}%",
                        str(f.encore_hits),
                        potency(f.encore_potency_min, f.encore_potency_max),
                    )
                    for f in result.brd_finales
                ],
            )
            ready_lines({"Radiant Encore"})
            print_follow_up_context(result.follow_up_context, stamp)
        if job == "machinist" or result.mch_wildfires or result.pet_deployments:
            emit_text("  Tools and Reassemble:")
            table(
                ("Action", "Uses", "Possible"),
                [
                    (c.name, str(c.uses), str(c.possible) if c.possible is not None else "n/a")
                    for c in execution.cooldowns
                    if c.name not in {"Reassemble", "Wildfire"}
                ]
                if execution
                else [],
            )
            emit_text("  Double Check/Checkmate maxima use recorded Blazing Shots and enemy windows.")
            emit_text("  Weaving constraints and buff alignment are not modelled.")
            emit_text()
            emit_text(f"  Reassemble: {uses('Reassemble')} uses")
            print_cooldown_timing(result.cooldown_timing)
            print_burst_alignment(result.burst_alignment, stamp)
            emit_text("\n  Wildfire:")
            emit_text(f"  Uses: {uses('Wildfire')}")
            table(
                ("Applied", "Detonated", "GCDs", "Landed potency", "End"),
                [
                    (
                        stamp(w.applied_seconds),
                        stamp(w.detonated_seconds) if w.detonated_seconds is not None else "none",
                        f"{w.landed_weaponskills}/6",
                        f"{w.potency:,.0f}",
                        "Detonator" if w.detonated_early else "Natural",
                    )
                    for w in result.mch_wildfires
                ],
                notes=[wildfire_note(w) for w in result.mch_wildfires],
            )
            emit_text("\n  Hypercharge:")
            h = (
                next((r for r in execution.ready if r.name == "Hypercharge"), None)
                if execution
                else None
            )
            if h and h.evidence_available:
                emit_text(f"  Uses: {len(h.windows)} | GCDs used: {h.uses}/{h.grants}")
                emit_text(
                    f"  Complete windows: {sum(w.uses == w.charges for w in h.windows)}/{len(h.windows)}"
                )
                table(
                    ("Started", "GCDs", "End"),
                    [
                        (stamp(w.start_seconds), f"{w.uses}/{w.charges}", w.end_reason)
                        for w in h.windows
                        if w.uses < w.charges
                    ],
                    blank_before=True,
                )
            else:
                emit_text(f"  Uses: {counts.get('Hypercharge', 0)} | Window evidence unavailable")
        if result.dnc_finishes or proc:
            emit_text(f"  Devilment: {uses('Devilment')} uses")
            ready_lines({"Starfall Dance"})
            emit_text(f"  Flourish: {uses('Flourish')} uses")
            print_cooldown_timing(result.cooldown_timing)
            if not result.burst_packages:
                print_burst_alignment(result.burst_alignment, stamp)
            emit_text("\n  Standard Finish:")
            emit_text(
                f"    Uses: {sum(1 for f in result.dnc_finishes if 'Standard Finish' in f.action)} | Finishing Move: {counts.get('Finishing Move', 0)} uses"
            )
            coverage_line("Standard Finish", indent="    ")
            for name, strength in result.dnc_initial_buffs:
                emit_text(f"    Pre-pull {name}: +{(strength - 1) * 100:.0f}% damage (inferred)")
            emit_text()
            ready_lines({"Last Dance"})
            emit_text(f"\n  Technical Step: {uses('Technical Step')} uses")
            table(
                ("Time", "Steps", "Hits", "Landed potency"),
                [
                    (
                        stamp(f.seconds),
                        str(f.steps) if f.steps is not None else "n/a",
                        str(f.hits),
                        f"{f.potency:,.0f}",
                    )
                    for f in result.dnc_finishes
                    if "Technical Finish" in f.action
                ],
            )
            emit_text()
            ready_lines({"Tillana", "Dance of the Dawn"})
            print_follow_up_context(result.follow_up_context, stamp)

        if not result.pld:
            print_job_packages(result.burst_packages, stamp, explanations=explanations, job=job,
                               hit_context=missing_hit_context(result))

    def job_effects():
        if has_job_sections:
            emit_text("\nCombos, ready effects and charges:")
        if result.pld:
            p = result.pld
            if p.combos is not None:
                if p.combos.losses:
                    emit_text("  Combo losses:")
                    table(("Action", "Uncomboed hits", "Base potency lost"),
                          [(c.name, str(c.hits), f"{c.potency_lost:,.1f}")
                           for c in sorted(p.combos.losses, key=lambda c: (-c.potency_lost, c.name))])
                    emit_text("  Base potency lost excludes overkill, buffs and penalties.")
                else:
                    emit_text("  No confirmed combo losses.")
                if p.combos.unconfirmed_hits:
                    hits = p.combos.unconfirmed_hits
                    emit_text(f"  Unconfirmed combo evidence: {hits} landed "
                          + ("hit" if hits == 1 else "hits"))
                    emit_text("  Unknown combo hits use a potency range from uncomboed to comboed.")
                if p.combos.inferred:
                    for inferred in sorted(p.combos.inferred, key=lambda c: c.seconds):
                        outcome = "comboed" if inferred.comboed else "uncomboed"
                        previous = inferred.previous_gcd or "previous GCD unavailable"
                        emit_text(f"  {stamp(inferred.seconds)} {previous} -> {inferred.name}: "
                              + f"{inferred.potency_lost:,.1f} estimated base potency lost "
                              + f"({outcome} inferred from normalized damage; combo field unavailable)")
            sequence_names = {"Atonement", "Supplication", "Sepulchre"}
            for label, effects in (
                ("Atonement sequences", [r for r in p.ready if r.name in sequence_names]),
                ("Other ready effects and spell charges", [r for r in p.ready
                                                          if r.name not in sequence_names]),
            ):
                if effects:
                    emit_text(f"\n  {label}:")
                    for r in effects:
                        line = ready_line(r)
                        expiries = [stamp(time) for time, reason in r.losses
                                    if reason.endswith("expired")]
                        notes = ()
                        if expiries:
                            value = f"{r.expired} expired"
                            if len(expiries) == 1 or not tooltip_context:
                                line = line.replace(value, value + " (" + ", ".join(expiries) + ")")
                            else:
                                notes = ((value, "Expired at:\n" + "\n".join(expiries)),)
                        emit_text("    " + line, notes=notes)
                        for time, reason in r.losses:
                            if reason.endswith("expired"):
                                continue
                            emit_text(f"      {stamp(time)}: {reason}")
        if result.war:
            w = result.war
            emit_text("  Surging Tempest:")
            uptime = f"{w.tempest_uptime:.2%}" if w.tempest_uptime is not None else "n/a"
            hit = f"{w.tempest_hits / w.total_hits:.2%}" if w.total_hits else "n/a"
            emit_text(f"    Uptime: {uptime} | Buffed attacks: {hit} ({w.tempest_hits}/{w.total_hits})")
            for time, name in w.tempest_missing:
                emit_text(f"      {stamp(time)} {name}")
            emit_text(f"    Avoidable potency lost: {w.tempest_lost_potency:,.1f}")
            emit_text("    Warnings exclude opening setup, setup after confirmed downtime and buff application gaps up to 1s.")
            print_combo_diagnostics(result.combos, stamp, heading=False)
        if job == "bard" or result.brd_songs or result.brd_potency_estimates:
            emit_text("  Songs and Repertoire:")
            coverage_line("Songs", "Song uptime")
            table(
                ("Song", "Uses", "Total duration"),
                [
                    (name, str(count), f"{dict(result.brd_song_durations).get(name, 0) * count:.1f}s")
                    for name, count in result.brd_songs
                ],
                blank_before=True,
            )
            if execution:
                for time in execution.repertoire_losses:
                    emit_text(
                        f"  {stamp(time)}: at least 1 unused Repertoire stack (Empyreal Arrow confirmed)"
                    )
            emit_text("\n  Apex Arrow and Pitch Perfect:")
            for estimate in result.brd_potency_estimates:
                if estimate.action == "Radiant Encore":
                    continue
                if estimate.action == "Pitch Perfect":
                    emit_text()
                hits_label = "hit" if estimate.uncertain_hits == 1 else "hits"
                if estimate.apex_uses:
                    ambiguous = sum(len(u.plausible_gauges) != 1 for u in estimate.apex_uses)
                    emit_text(
                        f"  {estimate.action}: {estimate.estimated_hits} hits | {ambiguous} uses with ambiguous potency ({estimate.uncertain_hits} affected {hits_label})"
                    )
                else:
                    emit_text(
                        f"  {estimate.action}: {estimate.estimated_hits} hits, {estimate.uncertain_hits} uncertain {'estimate' if estimate.uncertain_hits == 1 else 'estimates'}"
                    )
                table(
                    ("Time", "Plausible gauge", "Best fit", "Hits", "Landed potency"),
                    [
                        (
                            stamp(u.seconds),
                            "/".join(map(str, u.plausible_gauges)) or "outside expected range",
                            str(u.gauge),
                            str(u.hits),
                            f"{u.potency:,.0f}" if u.potency is not None else "n/a",
                        )
                        for u in estimate.apex_uses
                    ],
                )
                for hit in estimate.pitch_uncertain_hits:
                    detail = "plausible: " + " or ".join(hit.plausible_fits)
                    if len(hit.plausible_fits) == 1 and not hit.outside_expected:
                        emit_text(
                            f"    {stamp(hit.seconds)}: {hit.best_fit} (limited same-target references)"
                        )
                        continue
                    if (
                        hit.outside_expected
                        and hit.observed_damage is not None
                        and hit.lower_damage is not None
                        and hit.upper_damage is not None
                    ):
                        direction = "above" if hit.observed_damage > hit.upper_damage else "below"
                        detail = f"Damage: {hit.observed_damage:,.0f} | Expected: {hit.lower_damage:,.0f}-{hit.upper_damage:,.0f} ({hit.distance_from_bound_percent:.1f}% {direction} range)"
                    elif hit.outside_expected:
                        detail = "outside expected damage (range unavailable)"
                    emit_text(f"    {stamp(hit.seconds)}: best fit {hit.best_fit} | {detail}")
                if estimate.weak_reference_hits:
                    emit_text(
                        f"  {estimate.weak_reference_hits} hits had fewer than 3 same-target references"
                    )
        if job == "machinist" or result.mch_wildfires or result.pet_deployments:
            ready_lines({"Full Metal Field", "Excavator"})
            emit_text("\n  Automaton Queen and Battery:")
            rows = []
            for d in result.pet_deployments:
                hits = dict(d.landed_actions)
                gauge = str(d.gauge_spent) + ("~" if d.gauge_assumed or d.mch_gauge_inferred else "")
                rows.append(
                    (
                        "Pre-pull" if d.mch_prepull else stamp(d.timestamp_seconds),
                        gauge,
                        str(hits.get("Arm Punch", 0)),
                        str(hits.get("Roller Dash", 0)),
                        ", ".join(
                            {"Pile Bunker": "Bunker", "Crowned Collider": "Collider"}.get(name, name)
                            for name in d.mch_missing_finishers
                        )
                        or "-",
                        potency(d.potency_min, d.potency_max),
                    )
                )
            table(
                (
                    "Summoned",
                    "Battery",
                    "Arm Punch",
                    "Roller Dash",
                    "Missing Finisher(s)",
                    "Landed potency",
                ),
                rows,
            )
            for d in result.pet_deployments:
                if d.mch_overdrive_seconds is not None:
                    emit_text(f"  {stamp(d.mch_overdrive_seconds)} Queen Overdrive")
                if d.mch_gauge_inferred:
                    emit_text(f"  Opening Battery: {d.gauge_spent} (estimated from Queen damage)")
                elif d.gauge_assumed:
                    emit_text(f"  Opening Battery: {d.gauge_spent} (assumed carry-over, unconfirmed)")
            print_follow_up_context(result.follow_up_context, stamp)
            print_combo_diagnostics(result.combos, stamp, heading=False)
        if proc:
            emit_text("  Proc usage:")
            death_column = any(r.death_lost for r in proc.ready_procs)
            labels = (
                "Effect",
                "Random grants",
                "Flourish grants",
                "Uses",
                "Expired",
                "Overwritten",
                *(("Death",) if death_column else ()),
                "Remaining",
            )
            table(
                labels,
                [
                    (
                        r.name,
                        str(r.random_grants) if r.random_grants is not None else "n/a",
                        str(r.guaranteed_grants) if r.guaranteed_grants is not None else "n/a",
                        str(r.uses),
                        str(r.expired),
                        str(r.overwritten),
                        *((str(r.death_lost),) if death_column else ()),
                        str(r.remaining),
                    )
                    for r in proc.ready_procs
                ],
            )
            emit_text("  Effects active at fight end count as remaining, not lost.")
            emit_text()
            ready_lines({"Fan Dance IV"})
            losses = sorted(
                (time, name, reason) for r in proc.ready_procs for time, name, reason in r.losses
            )
            for reason, label in (
                ("expired", "Expired procs"),
                ("overwritten", "Overwritten procs"),
                ("death", "Procs lost on death"),
            ):
                matching = [(time, name) for time, name, why in losses if why == reason]
                if matching:
                    emit_text(f"\n  {label}:")
                    for time, name in matching:
                        emit_text(f"    {stamp(time)}: {name}")
            emit_text("\n  Esprit and Saber Dance:")
            saber = counts.get("Saber Dance", 0)
            dawn = counts.get("Dance of the Dawn", 0)
            emit_text(
                f"  Saber Dance: {saber} | Dance of the Dawn: {dawn} | Esprit spent: {50 * (saber + dawn):,}"
            )
            emit_text("  Esprit generation and overcap cannot be reconstructed exactly.")
        if result.dnc_finishes or proc:
            print_combo_diagnostics(result.combos, stamp, heading=False)

        if job == "bard" or result.brd_dots:
            emit_text("\n  DoT coverage and refreshes:")
            coverage_rows({"Caustic Bite", "Stormbite"})
            for dot in result.brd_dots:
                if dot.name == "Iron Jaws":
                    emit_text(f"  Iron Jaws: {dot.landed_uses} refresh hits | {dot.direct_potency:,.0f} potency")
            if not execution or not any(
                c.name in {"Caustic Bite", "Stormbite"} for c in execution.coverage
            ):
                emit_text("  Coverage unavailable (missing or multiple target instances).")

    def job_dot_totals():
        if result.pld or result.brd_dots:
            emit_text("\n  DoTs:")
        labels = ("DoT", "Applications", "Periodic ticks", "Application potency", "Periodic potency", "Total potency")
        if result.pld:
            circle = result.pld.circle
            table(labels,
                  [("Circle of Scorn", str(circle.applications), str(circle.ticks),
                    f"{circle.application_potency:,.1f}", f"{circle.tick_potency:,.1f}",
                    f"{circle.application_potency + circle.tick_potency:,.1f}")])
        if result.brd_dots:
            dots = sorted(
                (dot for dot in result.brd_dots if dot.name != "Iron Jaws"),
                key=lambda dot: {"Caustic Bite": 0, "Stormbite": 1}.get(dot.name, 2),
            )
            table(labels,
                  [(dot.name, str(dot.landed_uses), str(dot.ticks),
                    f"{dot.direct_potency:,.1f}", f"{dot.tick_potency:,.1f}",
                    f"{dot.direct_potency + dot.tick_potency:,.1f}") for dot in dots])
            if len(dots) > 1:
                total = sum(dot.direct_potency + dot.tick_potency for dot in dots)
                emit_text(f"  Total potency: {total:,.1f}")
            emit_text("  DoT ticks use the buffs and potion active when the DoT was applied or refreshed.")

    def job_downtime():
        if result.pld:
            p = result.pld
            emit_text("\nMelee downtime:")
            if p.ranged:
                count = len(p.ranged)
                total = sum(len(c.actions) for c in p.ranged)
                ranged_label = "ranged " + ("GCD" if total == 1 else "GCDs")
                emit_text(f"  {total} ranged " + ("GCD" if total == 1 else "GCDs")
                      + f" in {count} " + ("chain" if count == 1 else "chains") + ".",
                      notes=((ranged_label, ("Counts hard-cast Holy Spirit and Shield Lob. "
                              "Excludes instant Holy Spirit and the opener. "
                              "Gaps use cast-start times when available.")),) if tooltip_context else ())
            else:
                emit_text("  No ranged GCD chains identified.")
            holy_spirit_casts = {round(time, 6): kind for time, kind in p.holy_spirit_casts}

            def ranged_name(name, time):
                if name == "Shield Lob":
                    return "SL"
                if name != "Holy Spirit":
                    return name
                kind = holy_spirit_casts.get(round(time, 6), "unconfirmed")
                return f"HS ({'hard-cast' if kind == 'hard cast' else kind})"

            rows = []
            for c in p.ranged:
                before = (f"{ranged_name(c.previous, c.seconds - c.previous_gap)}"
                          + f" -> {c.previous_gap:.2f}s -> "
                          if c.previous and c.previous_gap is not None else "")
                time = c.seconds
                chain = ranged_name(c.actions[0], time)
                for gap, name in zip(c.gaps, c.actions[1:]):
                    time += gap
                    chain += f" -> {gap:.2f}s -> {ranged_name(name, time)}"
                after = (f" -> {c.following_gap:.2f}s -> "
                         + ranged_name(c.following, time + c.following_gap)
                         if c.following and c.following_gap is not None else "")
                rows.append((stamp(c.seconds), before + chain + after))
            if p.ranged:
                table(("Time", "GCD sequence"), rows)
                if not tooltip_context:
                    emit_text("  Instant Holy Spirit and the opening Holy Spirit are excluded.")
        if result.war:
            w = result.war
            emit_text("\nMelee downtime:")
            emit_text("  " + tomahawk_summary(w) if w.tomahawks else "  No ranged GCDs used.")
            for t in w.tomahawks:
                before = f"{t.previous} -> {t.previous_gap:.2f}s -> " if t.previous else ""
                after = f" -> {t.following_gap:.2f}s -> {t.following}" if t.following else ""
                chain = "T" + "".join(f" -> {gap:.2f}s -> T" for gap in t.gaps)
                emit_text(f"    {stamp(t.seconds)}: {before}{chain}{after}")

    job_cooldowns()
    job_effects()
    job_downtime()

    if result.potion.uses:
        p = result.potion
        emit_text("\nPotions:")
        item = p.item.name if p.item else "unidentified"
        emit_text(f"  Item: {item}")
        if p.window_totals:
            table(("Potion", "Start", "End", "Base potency", "Potion gain"),
                  [(str(i), stamp(w.start_seconds) if w.start_seconds is not None else "n/a",
                    stamp(w.end_seconds) if w.end_seconds is not None else "n/a",
                    decimal_potency(t.base_potency_min, t.base_potency_max),
                    decimal_potency(t.gained_potency_min, t.gained_potency_max))
                   for i, (w, t) in enumerate(zip(p.windows, p.window_totals), 1)],
                  indent="    ",
                  blank_before=False)
        else:
            for i, w in enumerate(p.windows, 1):
                if w.start_seconds is not None and w.end_seconds is not None:
                    emit_text(f"    Window {i}: {stamp(w.start_seconds)} - {stamp(w.end_seconds)}")
                else:
                    emit_text(f"    Window {i}: start/end unknown")
        base = (p.potted_potency_min + p.potted_potency_max) / 2
        gain = (p.gained_potency_min + p.gained_potency_max) / 2
        extra = f" (+{gain / base:.2%})" if base else ""
        base_text = potency(p.potted_potency_min, p.potted_potency_max)
        gain_text = potency(p.gained_potency_min, p.gained_potency_max)
        if p.window_totals:
            base_text = decimal_potency(p.potted_potency_min, p.potted_potency_max)
            gain_text = decimal_potency(p.gained_potency_min, p.gained_potency_max)
        emit_text(
            f"  Total base potency: {base_text} | Potion gain: {gain_text}{extra}"
        )
        if p.window_totals and not tooltip_context:
            emit_text("  Landed damage with a potion snapshot, including DoT ticks and auto-attacks. Base potency excludes the potion bonus.")
    if result.ghosted or result.reduced_damage_hits:
        emit_text("\nGhosted attacks and reduced hits:")
        blocked = []
        unexplained = []
        confirmed = {(time, name) for time, name, _, _ in ghosts}
        for entry in missing_hit_context(result):
            reason = entry[3]
            encounter_reason = (reason.startswith(("target at ", "target defeated", "target died",
                                                   "target stopped taking damage"))
                                or "HP lock" in reason or "untargetable" in reason
                                or reason == "downtime")
            (blocked if encounter_reason and (entry[0], entry[1]) not in confirmed
             else unexplained).append(entry)
        for label, entries in (("Ghosted hits", unexplained),
                               ("HP locks and downtime", blocked)):
            if entries:
                emit_text(f"\n  {label}:")
                table(("Time", "Action", "Target", "Reason"),
                      [(stamp(time), name, target or "n/a", reason)
                       for time, name, target, reason in entries])
        if result.reduced_damage_hits:
            emit_text("\n  Reduced-damage hits:")
            hits = sorted(result.reduced_damage_hits, key=lambda hit: hit.seconds)
            table(("Time", "Action", "Target", "Damage retained"),
                  [(stamp(hit.seconds), hit.action, hit.target or "n/a",
                    f"{hit.damage / (hit.damage + hit.overkill):.4%}") for hit in hits],
                  cell_notes={(row, 3): f"{hit.damage:,.0f}/{hit.damage + hit.overkill:,.0f} damage. "
                              + "Only damage needed to defeat the target is retained."
                              for row, hit in enumerate(hits)},
                  cell_states={(row, 3): "info" for row in range(len(hits))})
    emit_text("\nHit Bonus and Luck:")
    table(("Metric", "Baseline", "Recorded", "Adjusted"), [
        ("Hit Bonus", "-", f"{result.hit_bonus:+.2%}", f"{result.adjusted_hit_bonus:+.2%}"),
        ("Luck", f"{result.luck_baseline:.2%}", f"{result.luck_score:.2%}", f"{result.adjusted_luck_score:.2%}"),
    ], blank_before=False)
    h = result.random_hit_outcomes
    if h is not None:
        total = h.normal + h.direct + h.critical + h.critical_direct
        normal_baseline = (
            1
            - result.direct_gear_baseline
            - result.critical_gear_baseline
            + result.direct_critical_gear_baseline
        )
        table(
            ("Outcome", "Gear baseline", "Observed", "Difference", "Hits"),
            [
                (
                    name,
                    f"{baseline:.2%}",
                    f"{count / total:.2%}" if total else "n/a",
                    f"{100 * (count / total - baseline):+.2f} pp" if total else "n/a",
                    str(count),
                )
                for name, count, baseline in (
                    ("Normal Hit", h.normal, normal_baseline),
                    (
                        "Direct Hit",
                        h.direct,
                        result.direct_gear_baseline - result.direct_critical_gear_baseline,
                    ),
                    (
                        "Critical Hit",
                        h.critical,
                        result.critical_gear_baseline - result.direct_critical_gear_baseline,
                    ),
                    (
                        "Direct Critical Hit",
                        h.critical_direct,
                        result.direct_critical_gear_baseline,
                    ),
                )
            ],
            blank_before=False,
        )
    else:
        emit_text("  Random outcome breakdown unavailable (older/custom result).")
    if not tooltip_context:
        emit_text("  Guaranteed Direct Hits and Critical Hits count toward Hit Bonus, but are excluded from Luck and this table.")
        emit_text("  Reconstructed DoT ticks do not record DH or Crit outcomes, so they are excluded from Hit Bonus and Luck.")
        emit_text("  Adjusted values remove the expected benefit of other players' Direct Hit and Critical Hit rate buffs.")
    if job == "machinist":
        emit_text("  Wildfire has no hit bonus.")
    if proc:
        emit_text("\n  Dancer proc luck:")
        starting = "/".join(map(str, proc.starting_feathers)) or "unknown"
        emit_text(f"  Starting feathers: {starting} ({proc.starting_feathers_source})")
        rows = []
        initial_trials = 0
        initial_grants = 0
        initial_expected = 0.0
        known = True
        for r in proc.ready_procs:
            if r.name == "Threefold":
                continue
            n = sum(c for _, c in r.trials)
            initial_trials += n
            initial_expected += r.expected
            if r.random_grants is None:
                known = False
            else:
                initial_grants += r.random_grants
            rows.append(
                (
                    r.name,
                    str(n),
                    f"{r.expected:.1f}",
                    str(r.random_grants) if r.random_grants is not None else "n/a",
                    f"{r.random_grants / n:.1%}" if r.random_grants is not None and n else "n/a",
                )
            )
        rows.append(
            (
                "Initial GCD total",
                str(initial_trials),
                f"{initial_expected:.1f}",
                str(initial_grants) if known else "n/a",
                f"{initial_grants / initial_trials:.1%}" if known and initial_trials else "n/a",
            )
        )
        rows.append(
            (
                "Feather",
                str(proc.feather_trials),
                f"{proc.expected_feathers:.1f}",
                f"{proc.feather_successes_min}"
                if proc.feather_successes_min is not None
                else "n/a",
                f"{proc.feather_successes_min / proc.feather_trials:.1%}"
                if proc.feather_successes_min is not None and proc.feather_trials
                else "n/a",
            )
        )
        rows.append(
            (
                "Threefold",
                str(proc.fan_trials),
                f"{proc.expected_threefold:.1f}",
                str(proc.random_threefold) if proc.random_threefold is not None else "n/a",
                f"{proc.random_threefold / proc.fan_trials:.1%}"
                if proc.random_threefold is not None and proc.fan_trials
                else "n/a",
            )
        )
        table(
            ("Stage", "Opportunities", "Expected", "Observed", "Proc rate"), rows, blank_before=True
        )
        emit_text("  Feather observed count and proc rate are minimums supported by the log.")
        emit_text("  Each random stage: 50% expected. Ordinary GCD-to-Feather chain: 25%.")
        emit_text("  Flourish skips the unlock roll. Threefold rolls after spending a feather.")
        emit_text(f"  Feathers spent: {proc.feathers_used} | Ending gauge and overcap unlogged")
        emit_text("\n  Luck indices: 50 = average (approximate rarity, not proc rates)")
        for name, value in (
            ("Initial GCD", proc.initial_proc_luck),
            ("GCD-to-Feather chain", proc.feather_luck_min),
            ("Threefold", proc.threefold_luck),
        ):
            emit_text(
                f"    {name}: {value:.1f}/100" if value is not None else f"    {name}: unavailable"
            )
        emit_text(
            f"\n  Feather luck score: at least {proc.combined_feather_luck_min:.1f}/100"
            if proc.combined_feather_luck_min is not None
            else "  Feather luck score: unavailable (insufficient or inconsistent proc/resource evidence)"
        )
        emit_text("    50 = baseline | 100 = every random roll succeeded")
        emit_text("    Unlogged Feather overcap can increase the true score.")


    emit_text("\nAction totals and auto-attacks:")
    pet_names = {name for d in result.pet_deployments for name, _ in d.landed_actions}
    action_rows = [
        (
            a.name,
            str(a.uses) if a.uses is not None else "-",
            str(a.hits),
            potency(a.potency_min, a.potency_max),
        )
        for a in result.actions
    ]
    labels = ("Pet action" if pet_names else "Action", "Uses", "Hits/ticks", "Landed potency")
    shared_widths = [
        max(len(label), *(len(row[i]) for row in action_rows))
        for i, label in enumerate(labels)
    ] if action_rows else None
    for pet in (False, True):
        rows = [row for row in action_rows if (row[0] in pet_names) == pet]
        if rows:
            table(
                ("Pet action" if pet else "Action", *labels[1:]),
                rows, column_widths=shared_widths,
            )
    job_dot_totals()
    if result.auto_attacks:
        emit_text("\n  Auto-attacks:")
        table(("Action", "Hits", "Weapon delay", "Base potency per hit", "Landed potency"),
              [(a.name, str(a.hits), f"{a.weapon_delay_seconds:.2f}s",
                f"{a.potency_per_hit:.2f}", f"{a.total_potency:,.0f}")
               for a in result.auto_attacks])
    if result.unmatched:
        emit_text("\nUnmatched landed damage:")
        for name, count in result.unmatched:
            emit_text(f"  {name}: {count}")
    emit_text("\nData and assumptions:")
    emit_text(
        f"  Actions: valid since {result.actions_since}"
        if result.actions_since
        else "  Actions: custom snapshot"
    )
    emit_text(f"  Partition: {partition} | Ranking patch bracket: {bracket}")
    emit_text(
        "  Gear stats assumed | Party main-stat bonus: "
        + (
            f"{result.party_bonus_percent}% (recorded)"
            if result.party_bonus_percent is not None
            else "5% (assumed; older saved fight)"
        )
    )
    emit_text(f"  Targetable time: {result.targetable_time_source}")
    if result.combat_start_offset_seconds is not None:
        emit_text("  Timeline: FF Logs combat time "
              + f"({result.combat_start_offset_seconds:.3f}s pre-pull excluded).")
    elif result.encounter_id == 4550:
        emit_text("  Timeline: original dungeon start (combat-time metadata unavailable).")
    if result.echo_status:
        emit_text(
            f"  Echo: {'0%' if result.echo_status == 'absent' else result.echo_status}"
            + (" (12% damage normalised by 1.12)" if result.echo_status == "observed" else "")
        )
    for a, b in result.food_missing_windows:
        emit_text(f"  Without food: {stamp(a)} - {stamp(b)}")
    if job == "bard":
        emit_text("  Radiant Finale possible uses follow the 120s buff cycle.")
    if result.dnc_finishes:
        emit_text("  Finish damage snapshots the preceding buff state.")
    emit_text()
