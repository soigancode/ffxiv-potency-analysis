"""Compact human-readable reports. Formatting never enters calculation caches."""

from pathlib import Path

from .analysis.brd.dots import DOT_NAMES
from .analysis.execution import Coverage
from .analysis.mch.wildfire import MchWildfireSummary
from .analysis.models import AnalysisResult


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
) -> None:
    if not rows:
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
        print()
    print(line(labels))
    for i, row in enumerate(rows):
        print(line(row))
        if notes and notes[i]:
            for note_line in notes[i].splitlines():
                print(indent + "  " + note_line)


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
        f"{label}: {value}"
        for label, value in (
            ("Expired", effect.expired),
            ("Overwritten", effect.overwritten),
            ("Lost on death", getattr(effect, "death_lost", 0)),
            ("Remaining", effect.remaining if include_remaining else 0),
        )
        if value
    ]


def ready_line(effect):
    if not getattr(effect, "evidence_available", True):
        return f"{effect.name}: {effect.observed_uses} uses (grant evidence unavailable)"
    return " | ".join(
        [f"{effect.name}: {effect.uses}/{effect.grants} grants used", *loss_details(effect)]
    )


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
    result: AnalysisResult, *, directory: Path | None, anonymous: bool, rank: int | None
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
    print()
    print(
        f"Player: {cli._display_player_name(result.source_name, anonymous=anonymous)}"
        + (f" | Rank: {rank}" if rank is not None else "")
    )
    print(
        f"Fight: {cli._format_fight(result)} | Duration: {duration(result.duration_seconds)}"
        + (" (wipe)" if result.kill is False else "")
        + f" | Targetable: {targetable}"
    )
    print(
        f"Date: {cli._fight_date(directory, full_year=True) if directory else 'n/a'} (UTC) | Patch: {result.played_patch or bracket}"
        + (f" ({patch_source})" if patch_source and patch_source != "fight date" else "")
    )
    print(f"Gear: {gear} | Food: {food}")
    metrics = []
    if result.encounter_id in {4549, 4551}:
        metrics.append(f"DPS: {result.dps:,.1f}" if result.dps is not None else "DPS: n/a")
    elif (
        job in {"warrior", "machinist"}
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
    print(
        f"\nLanded potency: {potency(result.potency_min, result.potency_max)} | PPS: {cli._format_pps(result.pps_min, result.pps_max)} | "
        + " | ".join(metrics)
    )

    findings = []
    deaths = [w for w in result.status_windows if w.name == "Dead"]
    if deaths:
        findings.append(f"{len(deaths)} " + ("death" if len(deaths) == 1 else "deaths"))
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
                + f", {w.tempest_lost_potency:,.1f} potency lost"
            )
        if w.unused_expired_charges:
            findings.append(
                f"Inner Release: {w.unused_expired_charges} unused "
                + ("charge" if w.unused_expired_charges == 1 else "charges")
                + " at expiry"
            )
        for r in w.ready:
            if r.expired or r.overwritten:
                findings.append(
                    f"{r.name}: " + " | ".join(loss_details(r, include_remaining=False))
                )
        if w.tomahawks:
            findings.append(tomahawk_summary(w))
    if execution:
        for c in execution.coverage:
            gaps = reported_coverage_gaps(c)  # Opening setup remains in actual coverage.
            if gaps:
                findings.append(f"{c.name}: {sum(b - a for a, b in gaps):.1f}s targetable gaps")
        for r in execution.ready:
            if r.expired or r.overwritten or r.death_lost:
                findings.append(
                    f"{r.name}: " + " | ".join(loss_details(r, include_remaining=False))
                )
        for time in execution.repertoire_losses:
            findings.append(
                f"{stamp(time)}: at least 1 unused Repertoire stack (Empyreal Arrow confirmed)"
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
                f"{stamp(d.timestamp_seconds)} Queen: missing {' and '.join(d.mch_missing_finishers)}"
            )
    proc = result.dnc_procs
    if proc:
        for r in proc.ready_procs:
            if r.expired or r.overwritten or r.death_lost:
                findings.append(
                    f"{r.name}: " + " | ".join(loss_details(r, include_remaining=False))
                )
    ghosts = confirmed_ghosts(result)
    if ghosts:
        findings.append(
            f"{len(ghosts)} confirmed ghosted " + ("hit" if len(ghosts) == 1 else "hits")
        )
    if result.reduced_damage_hits:
        findings.append(
            f"{len(result.reduced_damage_hits)} reduced-damage "
            + ("hit" if len(result.reduced_damage_hits) == 1 else "hits")
        )
    if proc:
        findings.append(
            f"Feather luck score: at least {proc.combined_feather_luck_min:.1f}/100"
            if proc.combined_feather_luck_min is not None
            else "Feather luck score: unavailable (insufficient or inconsistent resource evidence)"
        )
    if result.unmatched:
        findings.append("Unmatched damage present: potency is incomplete")
    print("\nExecution summary:")
    for line in findings or ["No confirmed issues in this log."]:
        print("  " + line)

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
                print(f"  {stamp(a)} - {stamp(b)} {c.name} ({b - a:.1f}s targetable)")

    def ready_lines(selected, indent="  "):
        for r in execution.ready if execution else ():
            if r.name in selected:
                print(indent + ready_line(r))
                for time, reason in r.losses:
                    print(f"{indent}  {stamp(time)}: {reason}")

    def coverage_line(name, label=None, indent="  "):
        c = next((c for c in execution.coverage if c.name == name), None) if execution else None
        if c:
            uptime = (
                f"{c.covered_seconds / c.targetable_seconds:.2%}" if c.targetable_seconds else "n/a"
            )
            print(
                f"{indent}{label or 'Uptime'}: {uptime} | Missing time: {c.targetable_seconds - c.covered_seconds:.1f}s"
            )
            for a, b in reported_coverage_gaps(c):
                print(f"{indent}  {stamp(a)} - {stamp(b)}: {b - a:.1f}s targetable gap")

    if result.war:
        w = result.war
        print("\nSurging Tempest:")
        uptime = f"{w.tempest_uptime:.2%}" if w.tempest_uptime is not None else "n/a"
        hit = f"{w.tempest_hits / w.total_hits:.2%}" if w.total_hits else "n/a"
        print(f"  Uptime: {uptime} | Buffed attacks: {hit} ({w.tempest_hits}/{w.total_hits})")
        for time, name in w.tempest_missing:
            print(f"    {stamp(time)} {name}")
        print(f"  Avoidable potency lost: {w.tempest_lost_potency:,.1f}")
        print("  Opening setup, confirmed downtime setup, and application gaps up to 1s excluded from warnings.")
        print("\nInner Release and follow-ups:")
        print(f"  Infuriate: {w.infuriate_uses} uses")
        print(
            f"  Inner Release: {w.inner_release_uses}"
            + (
                f"/{cooldowns['Inner Release'].possible}"
                if "Inner Release" in cooldowns and cooldowns["Inner Release"].possible is not None
                else ""
            )
            + " uses (including pre-pull)"
        )
        print(
            f"  Free Fell Cleave/Decimate uses: {w.guaranteed_spenders}/{3 * w.inner_release_uses}"
        )
        for time, charges in w.expired_charges:
            noun = "charge" if charges == 1 else "charges"
            print(f"    {stamp(time)}: {charges} unused {noun} expired")
        print()
        for r in w.ready:
            print("  " + ready_line(r))
            for time, reason in r.losses:
                print(f"    {stamp(time)}: {reason}")
        print("\nMelee downtime:")
        print("  " + tomahawk_summary(w) if w.tomahawks else "  No ranged GCDs used.")
        for t in w.tomahawks:
            before = f"{t.previous} -> {t.previous_gap:.2f}s -> " if t.previous else ""
            after = f" -> {t.following_gap:.2f}s -> {t.following}" if t.following else ""
            chain = "Tomahawk" + "".join(f" -> {gap:.2f}s -> Tomahawk" for gap in t.gaps)
            print(f"    {stamp(t.seconds)}: {before}{chain}{after}")
    if job == "bard" or result.brd_songs or result.brd_potency_estimates:
        print("\nSongs and personal buffs:")
        for name in ("Raging Strikes", "Battle Voice"):
            print(f"  {name}: {uses(name)} uses")
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
                print(
                    f"  {stamp(time)}: at least 1 unused Repertoire stack (Empyreal Arrow confirmed)"
                )
        print("\nRadiant Finale and Encore:")
        print(
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
        print("\nDoT coverage:")
        coverage_rows({"Caustic Bite", "Stormbite"})
        if execution and any(c.name in DOT_NAMES for c in execution.coverage):
            print()
        for dot in sorted(
            result.brd_dots,
            key=lambda dot: {"Caustic Bite": 0, "Stormbite": 1, "Iron Jaws": 2}.get(dot.name, 3),
        ):
            if dot.name == "Iron Jaws":
                print(
                    f"  Iron Jaws: {dot.landed_uses} refresh hits | {dot.direct_potency:,.0f} potency"
                )
                continue
            print(
                f"  {dot.name}: {dot.landed_uses} application {'hit' if dot.landed_uses == 1 else 'hits'}, {dot.ticks} ticks | {dot.direct_potency:,.0f} application + {dot.tick_potency:,.0f} tick potency"
            )
        if not execution or not any(
            c.name in {"Caustic Bite", "Stormbite"} for c in execution.coverage
        ):
            print("  Coverage unavailable (missing or multiple target instances).")
        print("  DoTs snapshot buffs and potions at application or refresh.")
        print("\nApex Arrow and Pitch Perfect:")
        for estimate in result.brd_potency_estimates:
            if estimate.action == "Radiant Encore":
                continue
            if estimate.action == "Pitch Perfect":
                print()
            hits_label = "hit" if estimate.uncertain_hits == 1 else "hits"
            if estimate.apex_uses:
                ambiguous = sum(len(u.plausible_gauges) != 1 for u in estimate.apex_uses)
                print(
                    f"  {estimate.action}: {estimate.estimated_hits} hits | {ambiguous} uses with ambiguous potency ({estimate.uncertain_hits} affected {hits_label})"
                )
            else:
                print(
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
                    print(
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
                print(f"    {stamp(hit.seconds)}: best fit {hit.best_fit} | {detail}")
            if estimate.weak_reference_hits:
                print(
                    f"  {estimate.weak_reference_hits} hits had fewer than 3 same-target references"
                )
    if job == "machinist" or result.mch_wildfires or result.pet_deployments:
        print("\nTools and Reassemble:")
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
        print("  Double Check/Checkmate maxima use recorded Blazing Shots and enemy windows.")
        print("  Weaving constraints and buff alignment are not modelled.")
        print()
        print(f"  Reassemble: {uses('Reassemble')} uses")
        ready_lines({"Full Metal Field", "Excavator"})
        print("\nWildfire:")
        print(f"  Uses: {uses('Wildfire')}")
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
        print("\nHypercharge:")
        h = (
            next((r for r in execution.ready if r.name == "Hypercharge"), None)
            if execution
            else None
        )
        if h and h.evidence_available:
            print(f"  Uses: {len(h.windows)} | GCDs used: {h.uses}/{h.grants}")
            print(
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
            print(f"  Uses: {counts.get('Hypercharge', 0)} | Window evidence unavailable")
        print("\nAutomaton Queen and Battery:")
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
                print(f"  {stamp(d.mch_overdrive_seconds)} Queen Overdrive")
            if d.mch_gauge_inferred:
                print(f"  Opening Battery: {d.gauge_spent} (estimated from Queen damage)")
            elif d.gauge_assumed:
                print(f"  Opening Battery: {d.gauge_spent} (assumed carry-over, unconfirmed)")
    if result.dnc_finishes or proc:
        print("\nDances and personal buffs:")
        print(f"  Devilment: {uses('Devilment')} uses")
        ready_lines({"Starfall Dance"})
        print(f"  Flourish: {uses('Flourish')} uses")
        print("\n  Standard Finish:")
        print(
            f"    Uses: {sum(1 for f in result.dnc_finishes if 'Standard Finish' in f.action)} | Finishing Move: {counts.get('Finishing Move', 0)} uses"
        )
        coverage_line("Standard Finish", indent="    ")
        for name, strength in result.dnc_initial_buffs:
            print(f"    Pre-pull {name}: +{(strength - 1) * 100:.0f}% damage (inferred)")
        print()
        ready_lines({"Last Dance"})
        print(f"\n  Technical Step: {uses('Technical Step')} uses")
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
        print()
        ready_lines({"Tillana", "Dance of the Dawn"})
    if proc:
        print("\nProc usage:")
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
        print("  Effects active at fight end count as remaining, not lost.")
        print()
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
                print(f"\n  {label}:")
                for time, name in matching:
                    print(f"    {stamp(time)}: {name}")
        print("\nEsprit and Saber Dance:")
        saber = counts.get("Saber Dance", 0)
        dawn = counts.get("Dance of the Dawn", 0)
        print(
            f"  Saber Dance: {saber} | Dance of the Dawn: {dawn} | Esprit spent: {50 * (saber + dawn):,}"
        )
        print("  Esprit generation and overcap cannot be reconstructed exactly.")
        print("\nDancer proc luck:")
        starting = "/".join(map(str, proc.starting_feathers)) or "unknown"
        print(f"  Starting feathers: {starting} ({proc.starting_feathers_source})")
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
        print("  Feather observed count and proc rate are minimums supported by the log.")
        print("  Each random stage: 50% expected. Ordinary GCD-to-Feather chain: 25%.")
        print("  Flourish skips the unlock roll. Threefold rolls after spending a feather.")
        print(f"  Feathers spent: {proc.feathers_used} | Ending gauge and overcap unlogged")
        print("\n  Luck indices: 50 = average (approximate rarity, not proc rates)")
        for name, value in (
            ("Initial GCD", proc.initial_proc_luck),
            ("GCD-to-Feather chain", proc.feather_luck_min),
            ("Threefold", proc.threefold_luck),
        ):
            print(
                f"    {name}: {value:.1f}/100" if value is not None else f"    {name}: unavailable"
            )
        print(
            f"\n  Feather luck score: at least {proc.combined_feather_luck_min:.1f}/100"
            if proc.combined_feather_luck_min is not None
            else "  Feather luck score: unavailable (insufficient or inconsistent proc/resource evidence)"
        )
        print("    50 = baseline | 100 = every random roll succeeded")
        print("    Unlogged Feather overcap can increase the true score.")

    if result.potion.uses:
        p = result.potion
        print("\nPotions:")
        item = p.item.name if p.item else "unidentified"
        print(f"  Uses: {p.uses} | Item: {item}")
        for i, w in enumerate(p.windows, 1):
            if w.start_seconds is not None and w.end_seconds is not None:
                print(f"    Window {i}: {stamp(w.start_seconds)} - {stamp(w.end_seconds)}")
            else:
                print(f"    Window {i}: start/end unknown")
        base = (p.potted_potency_min + p.potted_potency_max) / 2
        gain = (p.gained_potency_min + p.gained_potency_max) / 2
        extra = f" (+{gain / base:.2%})" if base else ""
        print(
            f"  Potted base potency: {potency(p.potted_potency_min, p.potted_potency_max)} | Potency gained: {potency(p.gained_potency_min, p.gained_potency_max)}{extra}"
        )
    print("\nHit bonus and luck:")
    print(f"  Luck baseline: {result.luck_baseline:.2%}")
    for label, value in (
        ("Luck", result.luck_score),
        ("Adjusted Luck", result.adjusted_luck_score),
    ):
        print(
            f"  {label}: {value:.2%} ({100 * (value - result.luck_baseline):+.2f} percentage points vs baseline)"
        )
    print(f"  Hit Bonus: {result.hit_bonus:+.2%}")
    print(
        f"  Adjusted Hit Bonus: {result.adjusted_hit_bonus:+.2%} ({100 * (result.adjusted_hit_bonus - result.hit_bonus):+.2f} percentage points vs raw)"
    )
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
            ("Random outcome", "Hits", "Observed", "Gear baseline", "Difference"),
            [
                (
                    name,
                    str(count),
                    f"{count / total:.2%}" if total else "n/a",
                    f"{baseline:.2%}",
                    f"{100 * (count / total - baseline):+.2f} pp" if total else "n/a",
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
            blank_before=True,
        )
    else:
        print("  Random outcome breakdown unavailable (older/custom result).")
    print(
        "  Guaranteed Direct Hits and Critical Hits count toward Hit Bonus, but are excluded from Luck and this table."
    )
    print("  Periodic ticks without recorded outcomes are also excluded.")
    if job == "machinist":
        print("  Wildfire has no hit bonus.")
    print("\nDeaths and damage penalties:")
    for w in deaths:
        ending, separator, detail = w.end_reason.partition(": ")
        if ending == "resurrected":
            ending = "revived"
        print(
            f"  {stamp(w.start_seconds)}: died -> {stamp(w.end_seconds)}: {ending}"
            f" | Time dead: {w.end_seconds - w.start_seconds:.1f}s"
            + (f" | {detail}" if separator else "")
        )
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
                penalty_notes.append(
                    "Refreshed: " + ", ".join(stamp(t) for t in w.refresh_seconds)
                    if w.refresh_seconds else ""
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
        notes=penalty_notes,
        blank_before=bool(deaths),
    )
    if rows:
        print()
    for line in penalty_totals:
        print(line)
    if not deaths and not rows:
        print("  No deaths or recorded damage penalties.")
    elif rows:
        print("  Losses cover landed attacks. Missed attacks while dead are not estimated.")
    if result.ghosted or result.reduced_damage_hits:
        print("\nGhosted attacks and reduced hits:")
        endings = {
            (time, name): reason
            for name, events in result.ghosted_ending_times
            for time, reason in events
        }
        low = {
            (time, name): hp for name, events in result.ghosted_target_low_hp for time, hp in events
        }
        targets = {
            (time, name): target
            for name, events in result.ghosted_targets
            for time, target in events
        }
        print(f"  Confirmed ghosted hits: {len(ghosts)}")
        for time, name, target, reason in ghosts:
            print(
                f"    {stamp(time)} {name}" + (f" on {target}" if target else "") + f" ({reason})"
            )
        confirmed = {(t, n) for t, n, _, _ in ghosts}
        others = sorted(
            (t, n) for n, times in result.ghosted_times for t in times if (t, n) not in confirmed
        )
        if others:
            print("  HP-lock or other missing hits:")
            for t, n in others:
                reason = (
                    f"target at {low[t, n]} HP"
                    if (t, n) in low
                    else endings.get((t, n), "reason unconfirmed")
                )
                target = targets.get((t, n))
                print(f"    {stamp(t)} {n}" + (f" on {target}" if target else "") + f" ({reason})")
        if result.reduced_damage_hits:
            print(f"  Reduced-damage hits: {len(result.reduced_damage_hits)}")
            for hit in result.reduced_damage_hits:
                fraction = hit.damage / (hit.damage + hit.overkill)
                print(
                    f"    {stamp(hit.seconds)} {hit.action}"
                    + (f" on {hit.target}" if hit.target else "")
                    + f": {hit.damage:,.0f}/{hit.damage + hit.overkill:,.0f} damage ({fraction:.4%} potency retained, lethal overkill)"
                )
    print("\nAction totals:")
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
    if result.auto_attacks:
        print("\nAuto-attacks:")
        for a in result.auto_attacks:
            print(f"  {a.name}: {a.hits} hits | Weapon delay: {a.weapon_delay_seconds:.2f}s")
            print(
                f"  Base potency per hit: {a.potency_per_hit:.2f} | Landed potency: {a.total_potency:,.0f}"
            )
    if result.unmatched:
        print("\nUnmatched landed damage:")
        for name, count in result.unmatched:
            print(f"  {name}: {count}")
    print("\nData and assumptions:")
    print(
        f"  Actions: valid since {result.actions_since}"
        if result.actions_since
        else "  Actions: custom snapshot"
    )
    print(f"  Partition: {partition} | Ranking patch bracket: {bracket}")
    print(
        "  Gear stats assumed | Party main-stat bonus: "
        + (
            f"{result.party_bonus_percent}% (recorded)"
            if result.party_bonus_percent is not None
            else "5% (assumed; older saved fight)"
        )
    )
    print(f"  Targetable time: {result.targetable_time_source}")
    if result.echo_status:
        print(
            f"  Echo: {'0%' if result.echo_status == 'absent' else result.echo_status}"
            + (" (12% damage normalised by 1.12)" if result.echo_status == "observed" else "")
        )
    for a, b in result.food_missing_windows:
        print(f"  Without food: {stamp(a)} - {stamp(b)}")
    if cooldowns:
        print("  Standard cooldown maxima use full duration with initial charges ready.")
    if job == "bard":
        print("  Radiant Finale possible uses follow the 120s buff cycle.")
    if result.dnc_finishes:
        print("  Finish damage snapshots the preceding buff state.")
    print("  Adjusted metrics subtract expected external Crit/DH buff benefit.")
    print()
