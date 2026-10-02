"""Command-line interface for FFXIV potency tools."""

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Self, TypedDict

import httpx
from dotenv import load_dotenv

from .analysis import (
    AnalysisError,
    AnalysisResult,
    analyze_saved_fight,
)
from .analysis.cache import CACHE_FILENAME, cache_root
from .analysis.penalties import DamagePenaltySummary
from .datasets import job_code, load_manifest, select_set
from .fflogs import (
    FFLogsClient,
    FFLogsError,
    download_report_events,
    parse_report_url,
    refresh_fight_context,
    refresh_report_rankings,
)
from .fflogs.download import (
    refresh_checkpoint_context,
    refresh_encounter_damage_events,
    refresh_encounter_overkill_events,
    refresh_player_status_events,
    refresh_report_date,
    refresh_revival_buff_events,
    refresh_targetability_events,
)
from .fflogs.partitions import current_partition, fight_partition_patch, require_current_patch
from .fflogs.rankings import (
    accessible_ranked_sources,
    ranked_source,
    ranked_sources_at_positions,
    ranked_sources_in_range,
    validate_rank_positions,
    validate_rank_range,
)
from .fflogs.reference import (
    ReportReference,
    parse_report_selection,
    report_code_from_directory,
    report_directory_name,
    valid_report_code,
)
from .fflogs.selection import ReportFight, report_fights
from .jobguide.raid_buffs import update_raid_effects
from .jobguide.schema import ACTION_SCHEMA_VERSION
from .jobguide.snapshot import LATEST_KNOWN_PATCH, update_job_guide
from .jobs import JOB_NAMES, job_name

SUPPORTED_JOBS = {
    "war": "warrior", "warrior": "warrior",
    "brd": "bard", "bard": "bard",
    "mch": "machinist", "machinist": "machinist",
    "dnc": "dancer", "dancer": "dancer",
}
CURRENT_FIGHTS = {
    "m9s": 101,
    "m10s": 102,
    "m11s": 103,
    "m12sp1": 104,
    "m12sp2": 105,
    "umad": 1085,
    "dmu": 1085,
    "doomtrain": 1083,
    "enuo": 1084,
    "amt": 4550,
    "mistwake": 4549,
    "clyteum": 4551,
}
_SAVED_FIGHT_FILES = ("fight.json", "master-data.json", "damage-events.json", "cast-events.json")
_FIGHT_DIRECTORY = re.compile(r"fight-(\d+)")
_SOURCE_DIRECTORY = re.compile(r"source-(\d+)")
_RANK_RANGE = re.compile(r"(\d+)-(\d+)")


class _RankingStatusOptions(TypedDict, total=False):
    on_status: Callable[[str], None]
    on_progress: Callable[[int, int], None]


class _Progress(AbstractContextManager["_Progress"]):
    """Show completed fights on one terminal line, then remove it."""

    def __init__(self) -> None:
        self.width = 0
        self.enabled = sys.stderr.isatty()

    def __enter__(self) -> Self:
        return self

    def update(self, label: str, done: int, total: int, *, detail: str = "") -> None:
        if not self.enabled:
            return
        filled = round(20 * done / total)
        line = f"{label}: [{'#' * filled}{'-' * (20 - filled)}] {done}/{total}"
        if detail:
            line += f" - {detail}"
        sys.stderr.write("\r" + line.ljust(self.width))
        sys.stderr.flush()
        self.width = max(self.width, len(line))

    def message(self, label: str) -> None:
        if not self.enabled:
            return
        sys.stderr.write("\r" + label.ljust(self.width))
        sys.stderr.flush()
        self.width = max(self.width, len(label))

    def clear(self) -> None:
        if self.enabled and self.width:
            sys.stderr.write("\r" + " " * self.width + "\r")
            sys.stderr.flush()
            self.width = 0

    def __exit__(self, *args: object) -> None:
        self.clear()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ffxiv-potency")
    commands = parser.add_subparsers(dest="command", required=True)

    jobguide = commands.add_parser("jobguide", help="update all job guides and buffs, or one item")
    jobguide.add_argument("item", nargs="?", help="job name or abbreviation (BRD/MCH/DNC/WAR), or 'buffs'")
    jobguide.add_argument("--output", type=Path, default=Path("data"), help="output root")

    clear = commands.add_parser("clear", help="remove downloaded data")
    clear.add_argument(
        "item", nargs="?", choices=("logs", "cache"),
        help="remove logs or analysis cache; default removes both",
    )
    clear.add_argument("--output", type=Path, default=Path("data/logs"), help="logs directory")
    clear.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    research = commands.add_parser("research", help="download sample logs for a job")
    research.add_argument("job", help="combat job name or three-letter abbreviation")
    research.add_argument(
        "--output", type=Path, default=Path("data/research"), help="research root"
    )

    fflogs = commands.add_parser("fflogs", help="download an FF Logs fight")
    fflogs.add_argument("url", help="'limit', a report URL or ID, or a job such as BRD/MCH/DNC/WAR")
    fflogs.add_argument("fight", nargs="?", help="fight abbreviation such as m9s")
    fflogs.add_argument(
        "rank", nargs="?", help="one rank, an inclusive range, or comma-separated ranks"
    )
    fflogs.add_argument(
        "--partition", type=int,
        help="global leaderboard partition (Savage: 1, 2, 7, 8, 13, 14; Extremes: 1, 2, 7, 8 or 7, 8; Dancing Mad: 1, 2)",
    )
    fflogs.add_argument("--output", type=Path, default=Path("data/logs"), help="output root")

    compare = commands.add_parser("compare", help="download and compare FF Logs sources")
    compare.add_argument("urls", nargs="+", help="two to ten report URLs or IDs")
    compare.add_argument(
        "--actions", type=Path, help=f"override the job's default {LATEST_KNOWN_PATCH} actions.json"
    )
    compare.add_argument("--output", type=Path, default=Path("data/logs"), help="output root")

    analyse = commands.add_parser("analyse", help="download if needed and calculate potency")
    analyse.add_argument("source", help="saved source directory or FF Logs report URL or ID")
    analyse.add_argument(
        "--actions", type=Path, help=f"override the job's default {LATEST_KNOWN_PATCH} actions.json"
    )
    analyse.add_argument("--output", type=Path, default=Path("data/logs"), help="download root")
    for command in (analyse, compare, fflogs):
        command.add_argument("--gear", help="gear profile ID; default selects BiS by fight date")
    return parser


def _format_potency(minimum: float, maximum: float) -> str:
    if minimum == maximum:
        return f"{minimum:,.0f}"
    return f"{minimum:,.0f}-{maximum:,.0f}"


def _format_duration(seconds: float) -> str:
    total_seconds = round(seconds)
    minutes, remaining = divmod(total_seconds, 60)
    return f"{minutes:02d}m{remaining:02d}s"


def _format_timestamp(seconds: float) -> str:
    sign = "-" if seconds < 0 and round(abs(seconds)) > 0 else ""
    return sign + _format_duration(abs(seconds))


def _format_pps(minimum: float, maximum: float) -> str:
    if minimum == maximum:
        return f"{minimum:,.2f}"
    return f"{minimum:,.2f}-{maximum:,.2f}"


def _format_rate_comparison(rate: float, baseline: float) -> str:
    return f"{rate:.2%} ({(rate - baseline) * 100:+.2f}%)"


def _format_fight(result: AnalysisResult) -> str:
    suffix = f" ({result.encounter_id})" if result.encounter_id is not None else ""
    name = result.fight_name
    if result.encounter_id == 4549:
        name = "Mistwake"
    elif result.encounter_id == 4550:
        name = "Another Merchant's Tale"
    elif result.encounter_id == 4551:
        name = "The Clyteum"
    elif result.encounter_id == 1083:
        name = "Doomtrain"
    return f"{name}{suffix}"


def _display_player_name(name: str, *, anonymous: bool = False) -> str:
    anonymous = anonymous or name.casefold() == "anonymous" or re.fullmatch(r"Player \(\d+\)", name) is not None
    displayed = "Anonymous" if anonymous else name
    return f"\x1b[3m{displayed}\x1b[23m" if anonymous and sys.stdout.isatty() else displayed


def _penalty_detail(penalty: DamagePenaltySummary) -> str:
    if penalty.main_stat_reduction is not None and penalty.multiplier is not None:
        return (
            f"main stat -{penalty.main_stat_reduction}%; "
            f"~{(1 - penalty.multiplier) * 100:.1f}% potency reduction"
        )
    return (
        f"{(1 - penalty.multiplier) * 100:.0f}% reduction"
        if penalty.multiplier is not None else "effect unknown"
    )


def _penalty_impact(penalty: DamagePenaltySummary) -> str:
    detail = f"{penalty.affected_hits} landed hits affected"
    if penalty.lost_potency_min is not None and penalty.lost_potency_max is not None:
        detail += (
            f"; {_format_potency(penalty.lost_potency_min, penalty.lost_potency_max)} "
            "potency lost"
        )
    return detail


def _print_analysis(
    result: AnalysisResult, *, directory: Path | None = None,
    anonymous: bool = False, rank: int | None = None,
) -> None:
    print()
    print(f"Player: {_display_player_name(result.source_name, anonymous=anonymous)}")
    if rank is not None:
        print(f"Rank: {rank}")
    wipe = " (wipe)" if result.kill is False else ""
    print(f"Fight: {_format_fight(result)}")
    print(f"Duration: {_format_duration(result.duration_seconds)}{wipe}")
    if result.targetable_seconds is not None:
        print(f"Targetable time: {_format_duration(result.targetable_seconds)} ({result.targetable_time_source})")
        print(f"Excluded time: {_format_duration(max(0, result.duration_seconds - result.targetable_seconds))}")
    else:
        print(f"Targetable time: {result.targetable_time_source}")
    if directory is not None:
        partition, patch = _fight_provenance(directory)
        print(f"Date: {_fight_date(directory, full_year=True)} (UTC)")
        print(f"Partition: {partition}")
        patch_detail = f" ({result.patch_source})" if result.played_patch and result.patch_source else ""
        print(f"Patch: {result.played_patch or patch}{patch_detail}")
        if result.played_patch and result.played_patch != patch and patch != "n/a":
            print(f"Ranking patch bracket: {patch}")
    bonus = (f"{result.party_bonus_percent}%"
             if result.party_bonus_percent is not None else "5% (assumed; older saved fight)")
    if result.gear_name:
        print(f"Actions: valid since {result.actions_since}" if result.actions_since
              else "Actions: custom snapshot")
        print(f"Gear: {result.gear_name} ({result.gear_source})")
    if result.food is None:
        print("Food: None")
    else:
        note = "" if result.food.recorded else " (configured; not identified in fight events)"
        print(f"Food: {result.food.name}{note}")
        for begin, finish in result.food_missing_windows:
            print(f"  Without food: {_format_timestamp(begin)} - {_format_timestamp(finish)}")
    print(f"Party main-stat bonus: {bonus}")
    if result.echo_status == "observed":
        print("Echo: 12% (damage normalised by 1.12)")
    elif result.echo_status == "absent":
        print("Echo: 0%")
    elif result.echo_status == "unknown":
        print("Echo: unknown (initial combatant auras unavailable)")
    print(f"nDPS: {result.ndps:,.1f}" if result.ndps is not None else "nDPS: n/a")
    print(f"rDPS: {result.rdps:,.1f}" if result.rdps is not None else "rDPS: n/a")
    print(f"Landed damage events: {result.landed_damage_events}")
    print(f"  Matched action events: {result.matched_damage_events}")
    auto_hits = sum(attack.hits for attack in result.auto_attacks)
    print(f"  Matched auto-attacks: {auto_hits}")
    unmatched = result.landed_damage_events - result.matched_damage_events - auto_hits
    if unmatched > 0:
        print(f"  Unmatched damage events: {unmatched}")
    print(f"Landed potency: {_format_potency(result.potency_min, result.potency_max)}")
    print(f"Potency per second: {_format_pps(result.pps_min, result.pps_max)}")
    if result.status_windows or result.damage_penalties:
        print("\nDamage penalties:")
        printed_counts: set[str] = set()
        window_counts = {
            name: sum(window.name == name for window in result.status_windows)
            for name in {window.name for window in result.status_windows}
        }
        for penalty in result.damage_penalties:
            if penalty.main_stat_reduction is not None and penalty.multiplier is not None:
                strength = (
                    f" (main stat -{penalty.main_stat_reduction}%; "
                    f"~{(1 - penalty.multiplier) * 100:.1f}% potency reduction)"
                )
            else:
                strength = (
                    f" ({(1 - penalty.multiplier) * 100:.0f}% reduction)"
                    if penalty.multiplier is not None else ""
                )
            windows = tuple(w for w in result.status_windows if w.name == penalty.name)
            if not windows:
                print(
                    f"  {penalty.name}{strength}: first landed hit "
                    f"{_format_timestamp(penalty.first_observed_seconds)}, last landed hit "
                    f"{_format_timestamp(penalty.last_observed_seconds)} "
                    f"({_penalty_impact(penalty)}; exact application/removal not recorded)"
                )
        for window in result.status_windows:
            note = window.end_reason
            if window.refresh_seconds:
                times = ", ".join(_format_timestamp(at) for at in window.refresh_seconds)
                note = f"refreshed at {times}; {note}"
            print(
                f"  {window.name}: {_format_timestamp(window.start_seconds)} - "
                f"{_format_timestamp(window.end_seconds)} ({note})"
            )
            if window.name not in printed_counts and window_counts[window.name] == 1:
                for penalty in result.damage_penalties:
                    if penalty.name == window.name:
                        print(f"    {_penalty_detail(penalty)}; {_penalty_impact(penalty)}")
                        printed_counts.add(window.name)
                        break
        for penalty in result.damage_penalties:
            count = window_counts.get(penalty.name, 0)
            if count <= 1:
                continue
            print(
                f"  {penalty.name} total ({count} windows): "
                f"{_penalty_detail(penalty)}; {_penalty_impact(penalty)}"
            )
    visible_estimates = tuple(
        estimate for estimate in result.brd_potency_estimates
        if estimate.action != "Radiant Encore"
    )
    if visible_estimates:
        print("\nVariable potency:")
        for estimate in visible_estimates:
            if estimate.apex_uses:
                uncertain = sum(len(use.plausible_gauges) != 1 for use in estimate.apex_uses)
                print(f"  Apex Arrow: {len(estimate.apex_uses)} uses, {estimate.estimated_hits} hits, "
                      f"{uncertain} uses with ambiguous potency "
                      f"({estimate.uncertain_hits} affected hits)")
                for use in estimate.apex_uses:
                    if len(use.plausible_gauges) == 1:
                        note = f"{use.gauge} gauge"
                    elif use.plausible_gauges:
                        low, high = use.plausible_gauges[0], use.plausible_gauges[-1]
                        note = f"best estimate {use.gauge} gauge (plausible {low} - {high} gauge)"
                    else:
                        note = f"best estimate {use.gauge} gauge (outside expected damage range)"
                    hits_label = "hit" if use.hits == 1 else "hits"
                    potency_label = (
                        f", {use.potency:,.0f} total potency"
                        if use.potency is not None else ""
                    )
                    print(f"    {_format_timestamp(use.seconds)}: {use.hits} {hits_label}, "
                          f"{note}{potency_label}")
                if estimate.weak_reference_hits:
                    print(f"    {estimate.weak_reference_hits} hits had fewer than 3 "
                          "same-target reference hits")
                continue
            ambiguous_label = "hit" if estimate.uncertain_hits == 1 else "hits"
            line = (
                f"  {estimate.action}: {estimate.estimated_hits} hits, "
                f"{estimate.uncertain_hits} {ambiguous_label} with ambiguous potency"
            )
            if estimate.uncertain_hits and estimate.action != "Pitch Perfect":
                line += (
                    f" (closest alternatives differ by up to "
                    f"{estimate.uncertainty_potency:,.0f} potency in total)"
                )
            print(line)
            for hit in estimate.pitch_uncertain_hits:
                if hit.outside_expected:
                    note = f"closest fit: {hit.best_fit}; outside expected damage"
                elif len(hit.plausible_fits) > 1:
                    note = "plausible: " + " or ".join(hit.plausible_fits)
                else:
                    note = f"likely {hit.best_fit}; reference damage is uncertain"
                if hit.distance_from_bound_percent is not None:
                    position = "outside" if hit.outside_expected else "inside"
                    note += (f"; {hit.distance_from_bound_percent:.2f}% "
                             f"{position} closest bound")
                print(f"    {_format_timestamp(hit.seconds)}: {note}")
    if result.reduced_damage_hits:
        print("\nReduced damage hits:")
        for hit in sorted(result.reduced_damage_hits, key=lambda hit: hit.seconds):
            percentage = 100 * hit.damage / (hit.damage + hit.overkill)
            precision = 4 if percentage < 0.01 else 2
            print(
                f"  {_format_timestamp(hit.seconds)} {hit.action}"
                f"{' on ' + hit.target if hit.target else ''}: "
                f"{hit.damage:,.0f}/{hit.damage + hit.overkill:,.0f} damage "
                f"({percentage:.{precision}f}% potency counted)"
            )
    if result.ghosted:
        print("\nGhosted damaging casts:")
        events = sorted((time, name) for name, times in result.ghosted_times for time in times)
        targets = {
            (time, name): target
            for name, times in result.ghosted_targets for time, target in times
        }
        target_low_hp = {
            (time, name): hp
            for name, times in result.ghosted_target_low_hp
            for time, hp in times
        }
        endings = {
            (time, name): reason
            for name, times in result.ghosted_ending_times
            for time, reason in times
        }
        for time, name in events:
            hp = target_low_hp.get((time, name))
            note = (
                f" (target at {hp} HP)"
                if hp is not None
                else f" ({endings[(time, name)]})" if (time, name) in endings else ""
            )
            target = targets.get((time, name))
            print(f"  {_format_timestamp(time)} {name}"
                  f"{' on ' + target if target else ''}{note}")
    if result.potion.uses:
        print("\nPotions:")
        print(f"  Uses: {result.potion.uses}")
        if result.potion.item is not None:
            note = "" if result.potion.item.recorded else " (configured; not identified in fight events)"
            print(f"  Item: {result.potion.item.name}{note}")
        for index, window in enumerate(result.potion.windows, 1):
            if window.start_seconds is not None and window.end_seconds is not None:
                print(
                    f"  Window {index}: {_format_timestamp(window.start_seconds)} - {_format_timestamp(window.end_seconds)}"
                )
            elif window.observed_start_seconds is not None and window.observed_end_seconds is not None:
                print(
                    f"  Window {index}: start unknown; Medicated observed "
                    f"{_format_timestamp(window.observed_start_seconds)} - {_format_timestamp(window.observed_end_seconds)}"
                )
        print(
            "  Potted base potency: "
            f"{_format_potency(result.potion.potted_potency_min, result.potion.potted_potency_max)}"
        )
        print(
            "  Potency gained: "
            f"{_format_potency(result.potion.gained_potency_min, result.potion.gained_potency_max)}"
        )
    outcomes = result.hit_outcomes
    print("\nObserved hit outcomes:")
    print(f"  Normal Hit: {outcomes.normal}")
    for label, count, baseline, rate in (
        ("Direct Hit", outcomes.direct, result.direct_gear_baseline, outcomes.direct_rate),
        ("Critical Hit", outcomes.critical, result.critical_gear_baseline, outcomes.critical_rate),
        (
            "Direct Critical Hit",
            outcomes.critical_direct,
            result.direct_critical_gear_baseline,
            outcomes.critical_direct_rate,
        ),
    ):
        print(f"  {label}: {count}")
        print(f"  {label} gear baseline: {baseline:.2%}")
        print(f"  {label} rate: {_format_rate_comparison(rate, baseline)}")
    if outcomes.unknown:
        print(f"  Unknown outcome: {outcomes.unknown}")
    print(f"  Hit Bonus: {result.hit_bonus:+.2%}")
    print(f"  Adjusted Hit Bonus: {result.adjusted_hit_bonus:+.2%}")
    print(f"  Luck baseline: {result.luck_baseline:.2%}")
    print(f"  Luck score: {_format_rate_comparison(result.luck_score, result.luck_baseline)}")
    print(
        "  Adjusted luck score: "
        f"{_format_rate_comparison(result.adjusted_luck_score, result.luck_baseline)}"
    )
    print("\nActions:")
    dot_actions = {dot.name for dot in result.brd_dots}
    for action in result.actions:
        potency = _format_potency(action.potency_min, action.potency_max)
        uses = (
            f"{action.uses} {'use' if action.uses == 1 else 'uses'}, "
            if action.uses is not None
            else ""
        )
        hits = (
            f"{action.hits} hits/ticks" if action.name in dot_actions
            else f"{action.hits} {'hit' if action.hits == 1 else 'hits'}"
        )
        print(f"  {action.name}: {uses}{hits}, {potency} total potency")
    if result.war is not None:
        war = result.war
        print("\nSurging Tempest:")
        if war.tempest_uptime is not None:
            print(f"  Surging Tempest uptime: {war.tempest_uptime:.2%} of {war.tempest_targetable_seconds:.1f}s observed targetable time")
        coverage = f"{war.tempest_hits / war.total_hits:.2%}" if war.total_hits else "n/a"
        print(f"  Surging Tempest: {coverage} of landed hits ({war.tempest_hits}/{war.total_hits})")
        print(f"  Potency lost without Surging Tempest: {war.tempest_lost_potency:,.1f}")
        for seconds, name in war.tempest_missing:
            print(f"    {_format_duration(seconds)} {name} without Surging Tempest")
        print("\nInner Release and follow-ups:")
        print(f"  Inner Release: {war.inner_release_uses} uses (including pre-pull), {war.guaranteed_spenders} guaranteed spender casts")
        print(f"    Unused charges at expiry: {war.unused_expired_charges}")
        print(f"  Infuriate: {war.infuriate_uses} uses")
        for ready in war.ready:
            print(f"  {ready.name}: {ready.grants} ready grants (including pre-pull), {ready.uses} uses")
            print(f"    Lost: {ready.expired} expired, {ready.overwritten} overwritten. Remaining: {ready.remaining}")
        print("\nMelee downtime:")
        print(f"  Tomahawk: {sum(1 + len(use.gaps) for use in war.tomahawks)} uses")
        for use in war.tomahawks:
            previous = f"{use.previous} -> {use.previous_gap:.2f}s -> " if use.previous is not None else ""
            following = f" -> {use.following_gap:.2f}s -> {use.following}" if use.following is not None else ""
            chain = "Tomahawk" + "".join(f" -> {gap:.2f}s -> Tomahawk" for gap in use.gaps)
            print(f"  {_format_duration(use.seconds)}: {previous}{chain}{following}")
    if result.brd_songs:
        print("\nSongs:")
        averages = dict(result.brd_song_durations)
        for song, count in result.brd_songs:
            average = averages.get(song)
            duration = f", {average:.1f}s average duration" if average is not None else ""
            print(f"  {song}: {count} uses{duration}")
    if result.brd_finales:
        print("\nRadiant Finale (Coda consumed):")
        for finale in result.brd_finales:
            hits = f"{finale.encore_hits} {'hit' if finale.encore_hits == 1 else 'hits'}"
            potency = _format_potency(finale.encore_potency_min, finale.encore_potency_max)
            print(
                f"  {_format_timestamp(finale.timestamp_seconds)} {finale.coda} Coda, "
                f"Radiant Encore: {hits} ({potency} potency)"
            )
    if result.brd_dots:
        print("\nDamage over time:")
        for dot in result.brd_dots:
            if dot.ticks:
                print(
                    f"  {dot.name}: {dot.landed_uses} application hits, "
                    f"{dot.ticks} landed ticks, "
                    f"{dot.direct_potency:,.0f} application potency + "
                    f"{dot.tick_potency:,.0f} tick potency"
                )
    if result.auto_attacks:
        print("\nAuto-attacks:")
        for auto_attack in result.auto_attacks:
            print(
                f"  {auto_attack.name}: {auto_attack.hits} hits, "
                f"estimated {auto_attack.estimated_delay_seconds:.3f}s -> "
                f"{auto_attack.weapon_delay_seconds:.2f}s weapon delay, "
                f"{auto_attack.potency_per_hit:.2f} potency/hit, "
                f"{auto_attack.total_potency:,.0f} total potency"
            )
    if result.dnc_procs is not None:
        proc = result.dnc_procs
        print("\nDancer proc luck:")
        start = (str(proc.starting_feathers[0]) if len(proc.starting_feathers) == 1
                 else f"{min(proc.starting_feathers)}-{max(proc.starting_feathers)}")
        print(f"  Starting feathers: {start} ({proc.starting_feathers_source})")
        print("  Proc luck indices: 50 = expected luck (approximate rarity)")
        if proc.initial_proc_luck is not None:
            print(f"  Initial GCD proc luck: {proc.initial_proc_luck:.1f}/100")
        if proc.feather_luck_min is not None:
            print(f"  Feather-chain luck index: {proc.feather_luck_min:.1f}/100 "
                  "(minimum supported by the log)")
            print("    Unlogged Feather overcap can make the true score higher.")
        else:
            print("  Feather-chain luck index: unavailable (insufficient proc or resource evidence)")

        if proc.threefold_luck is not None:
            print(f"  Threefold proc luck: {proc.threefold_luck:.1f}/100")
        if proc.gcd_to_feather_chance is not None:
            print(f"  Ordinary GCD-to-Feather chain: {100 * proc.gcd_to_feather_chance:.1f}% expected")
            print("    Flourish skips the unlock roll. Threefold is a separate roll after spending a feather.")
        for ready in proc.ready_procs:
            if ready.name == "Threefold":
                continue
            opportunities = sum(count for _, count in ready.trials)
            sources = ", ".join(f"{count} {name}" for name, count in ready.trials) or "none"
            print(f"  {ready.name} opportunities: {opportunities} ({sources}), "
                  f"expected random grants: {ready.expected:.1f}")
            if ready.random_grants is not None:
                extra = ready.random_grants - ready.expected
                rate = (f", {100 * ready.random_grants / opportunities:.1f}% proc rate"
                        if opportunities else "")
                print(f"  {ready.name} random grants: {ready.random_grants} "
                      f"({extra:+.1f} vs expected){rate}")
                print(f"  {ready.name} from Flourish: {ready.guaranteed_grants}")
            else:
                print(f"  {ready.name} grants: unavailable (missing or unattributed buff events)")
            print(f"  {ready.name} proc GCD uses: {ready.uses}")
            if ready.random_grants is not None:
                print(f"    Consumed: {ready.random_consumed} random, "
                      f"{ready.guaranteed_consumed} Flourish")
                print(f"    Both effects consumed together: {ready.overlaps}")
                print(f"    Lost: {ready.overwritten} overwritten, {ready.expired} expired, "
                      f"{ready.death_lost} on death. Remaining: {ready.remaining}")
        if (proc.full_use_expected_feathers is not None
                and proc.full_use_expected_random_threefold is not None):
            print(f"  Full-use chain expectation: {proc.full_use_expected_feathers:.1f} feathers, "
                  f"{proc.full_use_expected_random_threefold:.1f} random Threefold procs "
                  "(assuming all ready effects and feathers are used, with no losses)")
        print(f"  Feather opportunities: {proc.feather_trials}, "
              f"expected successful rolls: {proc.expected_feathers:.1f}")
        print(f"  Feathers used: {proc.feathers_used}")
        if proc.feathers_gained_min is not None:
            unknown = "ending gauge and cap losses" if len(proc.starting_feathers) == 1 else "starting/ending gauge and cap losses"
            print(f"  Feathers gained: {proc.feathers_gained_min}-{proc.feathers_gained_max} "
                  f"possible ({unknown} are unlogged)")
            if proc.feather_successes_min is not None:
                print(f"  Successful Feather rolls: at least {proc.feather_successes_min} "
                      f"of {proc.feather_trials}. Exact count is unlogged.")
        else:
            print("  Feather gains: unavailable (incomplete resource evidence)")
        print(f"  Threefold random opportunities: {proc.fan_trials}, "
              f"expected procs: {proc.expected_threefold:.1f}")
        if proc.random_threefold is not None:
            extra = proc.random_threefold - proc.expected_threefold
            print(f"  Threefold random procs: {proc.random_threefold} ({extra:+.1f} vs expected)")
            if proc.fan_trials:
                print(f"  Threefold proc rate: {100 * proc.random_threefold / proc.fan_trials:.1f}%")
        else:
            print("  Threefold random procs: unavailable (missing or unattributed buff events)")
        print(f"  Threefold from Flourish: {proc.guaranteed_threefold}")
        print(f"  Fan Dance III uses: {proc.fan_three_uses}")
        threefold = next((r for r in proc.ready_procs if r.name == "Threefold"), None)
        if threefold is not None and threefold.random_grants is not None:
            print(f"    Consumed: {threefold.random_consumed} random, "
                  f"{threefold.guaranteed_consumed} Flourish")
            print(f"    Lost: {threefold.overwritten} overwritten, {threefold.expired} expired, "
                  f"{threefold.death_lost} on death. Remaining: {threefold.remaining}")

        print("  Feather luck score: "
              f"{proc.combined_feather_luck_min:.1f}/100 (minimum supported by the log)"
              if proc.combined_feather_luck_min is not None
              else "  Feather luck score: unavailable (insufficient proc or resource evidence)")
        print("    50 = expected rates, 100 = every roll succeeds across all three stages.")
        if proc.combined_feather_luck_min is not None:
            print("    Unlogged Feather overcap can make the true score higher.")

    if result.dnc_finishes:
        print("\nDancer finishes:")
        for name, strength in result.dnc_initial_buffs:
            print(f"  Pre-pull {name}: +{(strength - 1) * 100:.0f}% damage "
                  "(inferred from recorded multipliers)")
        for finish in result.dnc_finishes:
            steps = f" ({finish.steps} steps)" if finish.steps is not None else ""
            print(f"  {_format_timestamp(finish.seconds)} {finish.action}{steps}: "
                  f"{finish.hits} landed hits, {finish.potency:,.0f} potency")

    if result.mch_wildfires:
        print("\nWildfire:")
        for wildfire in result.mch_wildfires:
            started = _format_timestamp(wildfire.applied_seconds)
            ended = (
                _format_timestamp(wildfire.detonated_seconds)
                if wildfire.detonated_seconds is not None
                else "no detonation"
            )
            print(
                f"  {started} - {ended}: {wildfire.landed_weaponskills}/6 landed weaponskills, "
                f"{wildfire.potency:,.0f} potency"
                f"{' (detonated early)' if wildfire.detonated_early else ''}"
            )
    if result.pet_deployments:
        print("\nPet deployments:")
        for deployment in result.pet_deployments:
            missing = (
                f" (missing {' and '.join(deployment.mch_missing_finishers)})"
                if deployment.mch_missing_finishers
                else ""
            )
            overdrive = (
                f" (Queen Overdrive at {_format_timestamp(deployment.mch_overdrive_seconds)})"
                if deployment.mch_overdrive_seconds is not None
                else ""
            )
            print(
                f"  {'Pre-pull' if deployment.mch_prepull else _format_timestamp(deployment.timestamp_seconds)} "
                f"{deployment.actor}: "
                f"{deployment.gauge_spent} {deployment.gauge}"
                f"{' (estimated from Queen damage)' if deployment.mch_gauge_inferred else ''}"
                f"{' (assumed carry-over; unconfirmed by this report)' if deployment.gauge_assumed else ''}, "
                f"{_format_potency(deployment.potency_min, deployment.potency_max)} total potency"
                f"{missing}{overdrive}"
            )
    if result.unmatched:
        print("\nUnmatched landed damage:")
        for name, count in result.unmatched:
            print(f"  {name}: {count}")
    print()


def _print_comparison(results: Sequence[AnalysisResult]) -> None:
    print()


def _comparison_player_field(name: str, directory: Path) -> str:
    reference = _reference_from_directory(directory)
    anonymous = (
        (reference is not None and reference.report_code.startswith("a:"))
        or name.casefold() == "anonymous"
        or re.fullmatch(r"Player \(\d+\)", name) is not None
    )
    displayed = ("Anonymous" if anonymous else name)[:24]
    styled = _display_player_name(displayed, anonymous=anonymous)
    return styled + " " * (24 - len(displayed))


def _fight_date(directory: Path, *, full_year: bool = False) -> str:
    """Format the fight start date in UTC from FF Logs' absolute report time."""
    try:
        fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return "n/a"
    if not isinstance(fight, dict):
        return "n/a"
    report_start = fight.get("reportStartTime")
    fight_start = fight.get("startTime")
    if (not isinstance(report_start, (int, float)) or isinstance(report_start, bool)
            or not isinstance(fight_start, (int, float)) or isinstance(fight_start, bool)):
        return "n/a"
    try:
        return datetime.fromtimestamp((report_start + fight_start) / 1000, UTC).strftime(
            "%d/%m/%Y" if full_year else "%d/%m/%y"
        )
    except (OSError, OverflowError, ValueError):
        return "n/a"


def _fight_provenance(directory: Path) -> tuple[str, str]:
    try:
        fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
        rankings_path = directory / "rankings.json"
        rankings = (json.loads(rankings_path.read_text(encoding="utf-8"))
                    if rankings_path.is_file() else {})
    except (OSError, UnicodeError, ValueError):
        return "n/a", "n/a"
    return fight_partition_patch(fight, rankings)


def _compare_directories(
    directories: Sequence[Path], override: Path | None, progress: _Progress | None = None,
    *, rank_positions: Sequence[int] | None = None, skip_analysis_errors: bool = False,
    gear: str | None = None,
) -> tuple[tuple[int, str], ...]:
    if rank_positions is not None and len(rank_positions) != len(directories):
        raise ValueError("ranking positions must match the compared fights")
    jobs = [_source_job(directory) for directory in directories]
    if len(set(jobs)) != 1:
        raise ValueError(f"comparison requires the same job; received: {', '.join(jobs)}")
    actions_path = _actions_for_job(jobs[0], override)
    results = []
    compared_directories = []
    compared_ranks = []
    skipped: list[tuple[int, str]] = []
    if progress is not None:
        progress.update("Calculating potency", 0, len(directories))
    for index, directory in enumerate(directories, 1):
        try:
            _verify_supported_fight(directory)
            result = (analyze_saved_fight(directory, actions_path, gear=gear) if gear is not None
                      else analyze_saved_fight(directory, actions_path))
        except AnalysisError as exc:
            if not skip_analysis_errors or rank_positions is None:
                raise
            skipped.append((rank_positions[index - 1], str(exc)))
        else:
            results.append(result)
            compared_directories.append(directory)
            if rank_positions is not None:
                compared_ranks.append(rank_positions[index - 1])
        if progress is not None:
            progress.update("Calculating potency", index, len(directories))
    if not results:
        raise ValueError("none of the selected fights could be analyzed")
    encounters = {
        ("id", result.encounter_id)
        if result.encounter_id is not None
        else ("name", result.fight_name.casefold())
        for result in results
    }
    if len(encounters) != 1:
        fights = ", ".join(result.fight_name for result in results)
        raise ValueError(f"comparison requires the same fight; received: {fights}")
    if progress is not None:
        progress.clear()
    _print_comparison(results)
    print(f"Fight: {_format_fight(results[0])}")
    provenance = [_fight_provenance(directory) for directory in compared_directories]
    shared_provenance = rank_positions is not None and len(set(provenance)) == 1
    show_partition = not (rank_positions is not None
                          and results[0].encounter_id in {4549, 4550, 4551})
    if shared_provenance:
        partition, patch = provenance[0]
        if show_partition:
            print(f"Partition: {partition}")
        print(f"Patch: {patch}")
    provenance_labels = (() if shared_provenance else
                         (("Partition", "Patch") if show_partition else ("Patch",)))
    use_dps = results[0].encounter_id in {4549, 4551}
    combine_dps = jobs[0] in {"warrior", "machinist"} and all(
        result.rdps is not None and result.ndps is not None
        and f"{result.rdps:.1f}" == f"{result.ndps:.1f}" for result in results
    )
    dps_labels = ("DPS",) if use_dps else (("rDPS/nDPS",) if combine_dps else ("rDPS", "nDPS"))
    labels = ("Duration", "Targetable", *dps_labels,
              "Potency", "PPS", "aHB", "Luck", "aLuck",
              *provenance_labels, "Date")
    rows: list[tuple[str, ...]] = []
    for index, result in enumerate(results):
        partition, patch = provenance[index]
        provenance_values = (() if shared_provenance else
                             ((partition, patch) if show_partition else (patch,)))
        assumed_battery = any(deployment.gauge_assumed or deployment.mch_gauge_inferred
                              for deployment in result.pet_deployments)
        marker = "~" if assumed_battery else ""
        rows.append((
            _format_duration(result.duration_seconds),
            (("~" if "estimated" in result.targetable_time_source else "") + _format_duration(result.targetable_seconds)) if result.targetable_seconds is not None else "n/a",
            *((f"{result.dps:,.1f}" if result.dps is not None else "n/a",)
              if use_dps else (f"{result.rdps:,.1f}",) if combine_dps else (
                  f"{result.rdps:,.1f}" if result.rdps is not None else "n/a",
                  f"{result.ndps:,.1f}" if result.ndps is not None else "n/a",
              )),
            marker + _format_potency(result.potency_min, result.potency_max),
            marker + _format_pps(result.pps_min, result.pps_max),
            marker + f"{result.adjusted_hit_bonus:+.2%}",
            marker + f"{result.luck_score:.2%}",
            marker + f"{result.adjusted_luck_score:.2%}",
            *provenance_values,
            _fight_date(compared_directories[index]),
        ))
    widths = tuple(max(len(label), *(len(row[column]) for row in rows))
                   for column, label in enumerate(labels))
    separator = "  "
    rank_header = f"{'Rank':>4}{separator}" if rank_positions is not None else ""
    print(f"{rank_header}{'Player':<24}{separator}" + separator.join(
        label if label == "Date" else f"{label:>{width}}"
        for label, width in zip(labels, widths)
    ))
    for index, (result, row) in enumerate(zip(results, rows)):
        rank = f"{compared_ranks[index]:>4}{separator}" if rank_positions is not None else ""
        player = _comparison_player_field(result.source_name, compared_directories[index])
        print(f"{rank}{player}{separator}" + separator.join(
            f"{value:>{width}}" for value, width in zip(row, widths)
        ))
    if any(result.targetable_seconds is None for result in results):
        print("n/a Targetable time unavailable. PPS uses full duration for those logs.")
    if any("estimated" in result.targetable_time_source for result in results):
        print("~ Targetable time estimated from recorded enemy windows.")
    if any(deployment.gauge_assumed for result in results
           for deployment in result.pet_deployments):
        print("~ Potency, PPS, aHB, Luck, and aLuck include an unconfirmed 100 Battery Gauge carry-over.")
    if any(deployment.mch_gauge_inferred for result in results
           for deployment in result.pet_deployments):
        print("~ Potency, PPS, aHB, Luck, and aLuck include Battery estimated from Queen damage.")
    print()
    return tuple(skipped)


def _require_actions(path: Path, job: str) -> None:
    if not path.is_file():
        raise ValueError(
            f"actions snapshot does not exist: {path}; generate it with "
            f"'ffxiv-potency jobguide {job}'"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    snapshot_job = document.get("job") if isinstance(document, dict) else None
    if not isinstance(snapshot_job, str) or snapshot_job.casefold() != job:
        raise ValueError(f"actions snapshot {path} does not match the selected job {job!r}")
    version = document.get("schema_version")
    if version is not None and version != ACTION_SCHEMA_VERSION:
        raise ValueError(
            f"actions snapshot {path} has schema version {version!r}, but this installation "
            f"requires version {ACTION_SCHEMA_VERSION}; reinstall the current project in "
            f"your active environment and run 'ffxiv-potency jobguide {job}' again"
        )


def _source_job(directory: Path) -> str:
    """Identify the selected player's FF Logs subtype, never guess MCH."""
    master = json.loads((directory / "master-data.json").read_text(encoding="utf-8"))
    actors = master.get("actors", [])
    source_match = _SOURCE_DIRECTORY.fullmatch(directory.name)
    source_id = int(source_match.group(1)) if source_match else None
    if source_id is None:
        casts = json.loads((directory / "cast-events.json").read_text(encoding="utf-8"))
        player_ids = {actor.get("id") for actor in actors if actor.get("type") == "Player"}
        candidates = {
            event.get("sourceID") for event in casts if event.get("sourceID") in player_ids
        }
        if len(candidates) != 1:
            raise ValueError(
                f"cannot identify a single player in {directory}; use a selected FF Logs source"
            )
        source_id = candidates.pop()
    actor = next((actor for actor in actors if actor.get("id") == source_id), None)
    if not isinstance(actor, dict) or actor.get("type") != "Player":
        raise ValueError(f"source {source_id} is not a player in {directory}")
    subtype = actor.get("subType")
    if not isinstance(subtype, str) or not subtype.strip():
        raise ValueError(f"source {source_id} has no job in {directory}")
    normalized = subtype.casefold().replace(" ", "")
    return SUPPORTED_JOBS.get(normalized, normalized)


def _verify_supported_fight(directory: Path) -> None:
    fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
    rankings_path = directory / "rankings.json"
    rankings = (json.loads(rankings_path.read_text(encoding="utf-8"))
                if rankings_path.is_file() else {})
    try:
        require_current_patch(fight, rankings)
    except ValueError as exc:
        reference = _reference_from_directory(directory)
        if (not str(exc).startswith("cannot identify") or reference is None
                or not os.environ.get("FFLOGS_CLIENT_ID")
                or not os.environ.get("FFLOGS_CLIENT_SECRET")):
            raise
        refresh_report_date(reference, directory)
        fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
        require_current_patch(fight, rankings)


def _actions_for_job(job: str, override: Path | None) -> Path:
    if job not in SUPPORTED_JOBS.values():
        raise ValueError(f"job {job!r} is not supported yet; currently Bard, Machinist, Dancer, and Warrior are supported")
    if override is not None:
        path = override
    else:
        manifest, root = load_manifest(job)
        row = select_set(manifest, "action_sets", LATEST_KNOWN_PATCH)
        local = Path("data/jobs") / job_code(job) / row["file"]
        path = local if local.is_file() else root / row["file"]
    _require_actions(path, job)
    return path


def _saved_directory(output: Path, reference: ReportReference) -> Path:
    return (
        output
        / report_directory_name(reference.report_code)
        / f"fight-{reference.fight_id}"
        / f"source-{reference.source_id}"
    )


def _choose_number(label: str, count: int) -> int:
    while True:
        try:
            answer = input(f"Choose {label} [1-{count}]: ").strip()
        except EOFError as exc:
            raise ValueError(
                "report selection needs interactive input; use a URL with fight and source"
            ) from exc
        if answer.isdecimal() and 1 <= int(answer) <= count:
            return int(answer) - 1
        print(f"Enter a number from 1 to {count}.")


def _ranking_status_options(progress: _Progress) -> _RankingStatusOptions:
    if not progress.enabled:
        return {}
    counts: tuple[int, int] | None = None
    label = "Looking up ranks"

    def status(message: str) -> None:
        nonlocal label
        label = "Identifying players" if message.startswith("Identifying player") else "Looking up ranks"
        if counts is None:
            progress.message(message)
        else:
            progress.update(label, *counts)

    def update(done: int, total: int) -> None:
        nonlocal counts
        counts = done, total
        progress.update(label, done, total)

    return {"on_status": status, "on_progress": update}


def _report_fight_label(fight: ReportFight) -> str:
    duration = (f", {_format_duration(fight.duration_seconds)}"
                if fight.duration_seconds is not None else "")
    wipe = " (wipe)" if fight.kill is False else ""
    return f"{fight.name} (fight {fight.id}{duration}){wipe}"


def _select_report_reference(url: str) -> ReportReference:
    selection = parse_report_selection(url)
    if selection.fight_id is not None and selection.source_id is not None:
        return ReportReference(selection.report_code, selection.fight_id, selection.source_id)

    supported = set(CURRENT_FIGHTS.values())
    with _Progress() as progress:
        progress.message("Loading report fights and players...")
        fights = report_fights(selection.report_code)
    choices = [
        fight for fight in fights
        if fight.encounter_id in supported
        and (selection.source_id is None or any(
            player.id == selection.source_id for player in fight.players
        ))
    ]
    if selection.fight_id is None:
        if not choices:
            detail = (" with the selected player" if selection.source_id is not None else "")
            raise ValueError(f"this report has no supported fights{detail}")
        if len(choices) == 1:
            fight = choices[0]
            print(f"Fight: {_report_fight_label(fight)}")
        else:
            print("Fights:")
            for number, fight in enumerate(choices, 1):
                print(f"  {number}. {_report_fight_label(fight)}")
            fight = choices[_choose_number("fight", len(choices))]
    else:
        fight = next((row for row in choices if row.id == selection.fight_id), None)
        if fight is None:
            raise ValueError(f"fight {selection.fight_id} is not a supported fight in this report")

    players = [
        player for player in fight.players
        if player.job.casefold() in SUPPORTED_JOBS.values()
    ]
    if selection.source_id is not None:
        player = next((row for row in players if row.id == selection.source_id), None)
        if player is None:
            raise ValueError(
                f"source {selection.source_id} is not a supported player in fight {fight.id}"
            )
        return ReportReference(selection.report_code, fight.id, player.id)
    if not players:
        raise ValueError(f"fight {fight.id} has no supported BRD, MCH, DNC, or WAR players")
    if len(players) == 1:
        player = players[0]
        print(f"Player: {player.name} ({player.job}, source {player.id})")
    else:
        print("Players:")
        for number, player in enumerate(players, 1):
            print(f"  {number}. {player.name} ({player.job}, source {player.id})")
        player = players[_choose_number("player", len(players))]
    return ReportReference(selection.report_code, fight.id, player.id)


def _reference_from_directory(directory: Path) -> ReportReference | None:
    """Recover an FF Logs reference from the downloader's canonical path."""
    fight_match = _FIGHT_DIRECTORY.fullmatch(directory.parent.name)
    source_match = _SOURCE_DIRECTORY.fullmatch(directory.name)
    report_code = report_code_from_directory(directory.parent.parent.name)
    if fight_match is None or source_match is None or report_code is None:
        return None
    return ReportReference(
        report_code=report_code,
        fight_id=int(fight_match.group(1)),
        source_id=int(source_match.group(1)),
    )


def _resolve_analysis_directory(
    source: str, output: Path, *, announce: bool = True, include_targetability: bool = False
) -> Path:
    if source.startswith("https://"):
        reference = parse_report_url(source)
        directory = _saved_directory(output, reference)
    else:
        directory = Path(source)
        reference = _reference_from_directory(directory)

    if all((directory / filename).is_file() for filename in _SAVED_FIGHT_FILES):
        fight = json.loads((directory / "fight.json").read_text(encoding="utf-8"))
        if (fight.get("encounterID") == 105 and reference is not None
                and os.environ.get("FFLOGS_CLIENT_ID")
                and os.environ.get("FFLOGS_CLIENT_SECRET")
                and not (directory / "checkpoint-context.json").is_file()):
            refresh_checkpoint_context(reference, directory)
        if (reference is not None and os.environ.get("FFLOGS_CLIENT_ID")
                and os.environ.get("FFLOGS_CLIENT_SECRET")
                and ("friendlyPlayers" not in fight
                     or not (directory / "combatant-info-events.json").is_file())):
            refresh_fight_context(reference, directory)
        rankings_path = directory / "rankings.json"
        try:
            cached_rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            cached_rankings = None
        if reference is not None and not (
            isinstance(cached_rankings, dict)
            and cached_rankings.get("metric") == "ndps"
            and "rdps" in cached_rankings
            and (fight.get("encounterID") not in {4549, 4551} or "dps" in cached_rankings)
        ):
            refresh_report_rankings(reference, directory)
        if (include_targetability and fight.get("encounterID") in {4549, 4550, 4551}
                and reference is not None and os.environ.get("FFLOGS_CLIENT_ID")
                and os.environ.get("FFLOGS_CLIENT_SECRET")
                and not (directory / "encounter-damage-events.json").is_file()):
            refresh_encounter_damage_events(reference, directory)
        if (include_targetability and reference is not None
                and os.environ.get("FFLOGS_CLIENT_ID") and os.environ.get("FFLOGS_CLIENT_SECRET")
                and not (directory / "targetability-events.json").is_file()):
            refresh_targetability_events(reference, directory)
        if (include_targetability and reference is not None
                and os.environ.get("FFLOGS_CLIENT_ID") and os.environ.get("FFLOGS_CLIENT_SECRET")
                and not (directory / "encounter-overkill-events.json").is_file()):
            refresh_encounter_overkill_events(reference, directory)
        if (reference is not None
                and os.environ.get("FFLOGS_CLIENT_ID") and os.environ.get("FFLOGS_CLIENT_SECRET")
                and not (directory / "life-events.json").is_file()):
            refresh_player_status_events(reference, directory)
        if (reference is not None
                and os.environ.get("FFLOGS_CLIENT_ID") and os.environ.get("FFLOGS_CLIENT_SECRET")
                and not (directory / "revival-buff-events.json").is_file()):
            refresh_revival_buff_events(reference, directory)
        return directory
    if reference is None:
        raise ValueError(
            f"saved fight is incomplete: {directory}; pass an FF Logs URL or use the canonical "
            "data/logs/<report>/fight-<id>/source-<id> path to download it"
        )
    download_root = output if source.startswith("https://") else directory.parents[2]
    download = download_report_events(reference, download_root)
    if announce:
        print(f"Saved fight data: {download.directory}")
    return download.directory


class _GearOptions(TypedDict, total=False):
    gear: str


def _download_and_compare(
    urls: Sequence[str], output: Path, actions: Path | None, progress: _Progress,
    *, rank_positions: Sequence[int] | None = None, skip_analysis_errors: bool = False,
    gear: str | None = None,
) -> tuple[tuple[int, str], ...]:
    # A source may appear more than once in a comparison; only one worker may
    # write its files, while the result still appears in each requested position.
    unique_urls = list(dict.fromkeys(urls))
    directories_by_url: dict[str, Path] = {}
    failures_by_url: dict[str, str] = {}
    progress.update("Loading fight data", 0, len(urls))
    with ThreadPoolExecutor(max_workers=min(3, len(unique_urls))) as executor:
        pending = {
            executor.submit(_resolve_analysis_directory, url, output, announce=False): url
            for url in unique_urls
        }
        for finished in as_completed(pending):
            url = pending[finished]
            try:
                directories_by_url[url] = finished.result()
            except FFLogsError as exc:
                if not skip_analysis_errors or rank_positions is None:
                    raise
                failures_by_url[url] = str(exc)
            completed = sum(url in directories_by_url or url in failures_by_url for url in urls)
            progress.update("Loading fight data", completed, len(urls))
    skipped = tuple(
        (rank_positions[index], failures_by_url[url])
        for index, url in enumerate(urls) if url in failures_by_url
    ) if rank_positions is not None else ()
    directories = [directories_by_url[url] for url in urls if url in directories_by_url]
    compared_ranks = tuple(
        rank_positions[index] for index, url in enumerate(urls) if url in directories_by_url
    ) if rank_positions is not None else None
    if not directories:
        raise FFLogsError("none of the selected ranked fights could be downloaded")
    gear_options: _GearOptions = {"gear": gear} if gear is not None else {}
    if progress.enabled:
        if compared_ranks is None:
            _compare_directories(directories, actions, progress, **gear_options)
        elif skip_analysis_errors:
            return skipped + _compare_directories(
                directories, actions, progress, rank_positions=compared_ranks,
                skip_analysis_errors=True, **gear_options,
            )
        else:
            _compare_directories(directories, actions, progress, rank_positions=compared_ranks, **gear_options)
    else:
        if compared_ranks is None:
            _compare_directories(directories, actions, **gear_options)
        elif skip_analysis_errors:
            return skipped + _compare_directories(
                directories, actions, rank_positions=compared_ranks,
                skip_analysis_errors=True, **gear_options,
            )
        else:
            _compare_directories(directories, actions, rank_positions=compared_ranks, **gear_options)
    return ()


def _compare_ranked_references(
    ranked: tuple[tuple[int, ReportReference], ...],
    skipped: tuple[tuple[int, str], ...],
    output: Path, progress: _Progress, *, gear: str | None = None,
) -> None:
    """Compare selected leaderboard entries and show skipped ranks."""
    urls = [
        f"https://www.fflogs.com/reports/{reference.report_code}"
        f"?fight={reference.fight_id}&source={reference.source_id}"
        for _, reference in ranked
    ]
    analysis_skipped = _download_and_compare(
        urls, output, None, progress,
        rank_positions=tuple(rank for rank, _ in ranked),
        skip_analysis_errors=True, **({"gear": gear} if gear is not None else {}),
    )
    skipped_ranks = (*skipped, *analysis_skipped)
    if skipped_ranks:
        print("Skipped ranks: " + ", ".join(
            f"{rank} ({reason})" for rank, reason in skipped_ranks
        ))
        print()


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    try:
        if args.command == "research":
            code = job_code(args.job)
            if code not in JOB_NAMES:
                raise ValueError(f"unknown job {args.job!r}; choose: {', '.join(JOB_NAMES)}")
            output = args.output / code
            saved = failures = 0
            # Fight aliases share a leaderboard. Visit each encounter only once.
            encounters = dict.fromkeys(CURRENT_FIGHTS.values())
            with _Progress() as progress:
                for encounter_id in encounters:
                    fight = next(name for name, id_ in CURRENT_FIGHTS.items() if id_ == encounter_id)
                    try:
                        ranked, skipped = accessible_ranked_sources(
                            encounter_id, job_name(code), limit=3,
                            partition=1 if encounter_id in {101, 103} else None,
                            **_ranking_status_options(progress),
                        )
                    except (FFLogsError, httpx.HTTPError) as exc:
                        progress.clear()
                        print(f"{fight}: {exc}", file=sys.stderr)
                        failures += 1
                        continue
                    progress.clear()
                    for rank, reason in skipped:
                        print(f"{fight}: skipped rank {rank}: {reason}", file=sys.stderr)
                    references = dict.fromkeys(reference for _, reference in ranked)
                    progress.update("Downloading logs", 0, len(references), detail=fight)
                    with ThreadPoolExecutor(max_workers=min(3, len(references))) as executor:
                        pending = {
                            executor.submit(
                                _resolve_analysis_directory,
                                f"https://www.fflogs.com/reports/{reference.report_code}"
                                f"?fight={reference.fight_id}&source={reference.source_id}",
                                output, announce=False, include_targetability=True,
                            ): reference
                            for reference in references
                        }
                        for completed, future in enumerate(as_completed(pending), 1):
                            reference = pending[future]
                            ranks = ",".join(str(rank) for rank, ref in ranked if ref == reference)
                            try:
                                directory = future.result()
                            except (FFLogsError, httpx.HTTPError, OSError, ValueError) as exc:
                                progress.clear()
                                print(f"{fight} rank {ranks}: {exc}", file=sys.stderr)
                                failures += 1
                            else:
                                saved += 1
                                progress.clear()
                                print(f"{fight} rank {ranks}: {directory}")
                            progress.update("Downloading logs", completed, len(references), detail=fight)
            print(f"Saved {saved} research logs in {output}.")
            return 1 if failures else 0

        if args.command == "clear":
            logs = args.output
            cache = cache_root(logs)
            targets = ([logs] if args.item == "logs" else [cache]
                       if args.item == "cache" else [logs, cache])
            for directory in targets:
                if directory.is_symlink():
                    raise ValueError(f"data directory must not be a symbolic link: {directory}")
                if directory.exists() and not directory.is_dir():
                    raise ValueError(f"data path is not a directory: {directory}")
            legacy_caches = []
            if args.item == "cache" and logs.is_dir() and not logs.is_symlink():
                for root, _, filenames in os.walk(logs, followlinks=False):
                    if CACHE_FILENAME in filenames:
                        legacy_caches.append(Path(root) / CACHE_FILENAME)
            existing = [directory for directory in targets if directory.exists()]
            label = ("saved logs" if args.item == "logs" else "cached analysis"
                     if args.item == "cache" else "saved logs and cached analysis")
            if not existing and not legacy_caches:
                print(f"No {label} to clear.")
                return 0
            if not args.yes:
                try:
                    locations = ", ".join(str(directory) for directory in existing + legacy_caches)
                    answer = input(f"Delete all {label} in {locations}? [y/N] ")
                except EOFError:
                    answer = ""
                if answer.strip().casefold() not in {"y", "yes"}:
                    print("Cancelled.")
                    return 0
            for directory in existing:
                for item in directory.iterdir():
                    if item.is_dir() and not item.is_symlink():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
            for path in legacy_caches:
                path.unlink(missing_ok=True)
            print(f"Cleared {label}.")
            return 0

        if args.command == "compare":
            if not 2 <= len(args.urls) <= 10:
                raise ValueError("compare requires two to ten FF Logs URLs or IDs")
            urls = []
            for source in args.urls:
                reference = _select_report_reference(source)
                urls.append(
                    f"https://www.fflogs.com/reports/{reference.report_code}"
                    f"?fight={reference.fight_id}&source={reference.source_id}"
                )
            with _Progress() as progress:
                _download_and_compare(urls, args.output, args.actions, progress, gear=args.gear)
            return 0

        if args.command == "analyse":
            source = args.source
            if source.startswith("https://") or (valid_report_code(source)
                                                 and not Path(source).exists()):
                reference = _select_report_reference(source)
                source = (
                    f"https://www.fflogs.com/reports/{reference.report_code}"
                    f"?fight={reference.fight_id}&source={reference.source_id}"
                )
            with _Progress() as progress:
                progress.update("Loading fight data", 0, 1)
                directory = _resolve_analysis_directory(
                    source, args.output, announce=not progress.enabled,
                    include_targetability=True,
                )
                progress.update("Loading fight data", 1, 1)
                job = _source_job(directory)
                actions_path = _actions_for_job(job, args.actions)
                _verify_supported_fight(directory)
                progress.update("Calculating potency", 0, 1)
                result = (analyze_saved_fight(directory, actions_path, gear=args.gear) if args.gear is not None
                          else analyze_saved_fight(directory, actions_path))
                progress.update("Calculating potency", 1, 1)
            reference = _reference_from_directory(directory)
            _print_analysis(
                result, directory=directory,
                anonymous=reference is not None and reference.report_code.startswith("a:"),
            )
            return 0

        if args.command == "fflogs":
            if args.url.casefold() == "limit":
                if args.fight is not None or args.rank is not None or args.partition is not None:
                    raise ValueError("fflogs limit takes no fight or rank")
                with FFLogsClient.from_environment() as client:
                    usage = client.rate_limit()
                print("FF Logs API usage:")
                print(f"  Spent this hour: {usage.points_spent:,.2f} / "
                      f"{usage.limit_per_hour:,} points")
                print(f"  Resets in: {_format_duration(usage.resets_in_seconds)}")
                return 0
            if args.fight is not None:
                job = SUPPORTED_JOBS.get(args.url.casefold())
                if job is None:
                    raise ValueError(
                        f"unsupported job {args.url!r}; use BRD, MCH, DNC, or WAR"
                    )
                encounter_id = CURRENT_FIGHTS.get(args.fight.casefold())
                if encounter_id is None:
                    raise ValueError(
                        f"unknown fight {args.fight!r}; choose: {', '.join(CURRENT_FIGHTS)}"
                    )
                current_partition(encounter_id, args.partition)
                rank_range = _RANK_RANGE.fullmatch(args.rank) if args.rank is not None else None
                if rank_range is not None:
                    first, last = map(int, rank_range.groups())
                    validate_rank_range(first, last)
                    with _Progress() as progress:
                        progress.message("Connecting to FF Logs...")
                        ranked, skipped = ranked_sources_in_range(
                            encounter_id, job, first, last, partition=args.partition,
                            **_ranking_status_options(progress),
                        )
                        _compare_ranked_references(ranked, skipped, args.output, progress, gear=args.gear)
                    return 0
                if args.rank is not None and "," in args.rank:
                    pieces = args.rank.split(",")
                    if any(not piece.isdecimal() for piece in pieces):
                        raise ValueError("ranks must be comma-separated positive numbers")
                    positions = tuple(int(piece) for piece in pieces)
                    validate_rank_positions(positions)
                    with _Progress() as progress:
                        progress.message("Connecting to FF Logs...")
                        ranked, skipped = ranked_sources_at_positions(
                            encounter_id, job, positions, partition=args.partition,
                            **_ranking_status_options(progress),
                        )
                        _compare_ranked_references(ranked, skipped, args.output, progress, gear=args.gear)
                    return 0
                if args.rank is not None:
                    if not args.rank.isdecimal() or int(args.rank) < 1:
                        raise ValueError("rank must be a positive number")
                    rank = int(args.rank)
                    with _Progress() as progress:
                        progress.message("Connecting to FF Logs...")
                        reference = ranked_source(
                            encounter_id, job, rank, partition=args.partition,
                            **_ranking_status_options(progress),
                        )
                        url = (
                            f"https://www.fflogs.com/reports/{reference.report_code}"
                            f"?fight={reference.fight_id}&source={reference.source_id}"
                        )
                        progress.update("Loading fight data", 0, 1)
                        directory = _resolve_analysis_directory(
                            url, args.output, announce=not progress.enabled,
                            include_targetability=True,
                        )
                        progress.update("Loading fight data", 1, 1)
                        actions_path = _actions_for_job(job, None)
                        _verify_supported_fight(directory)
                        progress.update("Calculating potency", 0, 1)
                        result = (analyze_saved_fight(directory, actions_path, gear=args.gear) if args.gear is not None
                          else analyze_saved_fight(directory, actions_path))
                        progress.update("Calculating potency", 1, 1)
                    _print_analysis(
                        result, directory=directory, rank=rank,
                        anonymous=reference.report_code.startswith("a:"),
                    )
                    return 0
                with _Progress() as progress:
                    progress.message("Connecting to FF Logs...")
                    ranked, skipped = accessible_ranked_sources(
                        encounter_id, job, partition=args.partition,
                        **_ranking_status_options(progress),
                    )
                    _compare_ranked_references(ranked, skipped, args.output, progress, gear=args.gear)
                return 0
            if args.rank is not None:
                raise ValueError("a rank requires a job and fight abbreviation")
            if args.partition is not None:
                raise ValueError("--partition requires a job and fight abbreviation")
            reference = _select_report_reference(args.url)
            with _Progress() as progress:
                progress.update("Loading fight data", 0, 1)
                download = download_report_events(reference, args.output)
                progress.update("Loading fight data", 1, 1)
            print(f"Saved fight data: {download.directory}")
            print(f"Damage events: {download.damage_event_count}")
            print(f"Cast events: {download.cast_event_count}")
            return 0

        if args.item is None:
            for job in dict.fromkeys(SUPPORTED_JOBS.values()):
                result = update_job_guide(
                    job=job, patch=LATEST_KNOWN_PATCH, output_root=args.output,
                )
                print(f"Saved source: {result.source}")
                print(f"Wrote {result.action_count} actions: {result.actions}")
            output = update_raid_effects(args.output)
            print(f"Saved raid effects: {output}")
            return 0

        if args.item.casefold() == "buffs":
            output = update_raid_effects(args.output)
            print(f"Saved raid effects: {output}")
            return 0

        job = SUPPORTED_JOBS.get(args.item.casefold())
        if job is None:
            raise ValueError(f"unsupported job {args.item!r}; use BRD, MCH, DNC, WAR, or buffs")
        result = update_job_guide(
            job=job,
            patch=LATEST_KNOWN_PATCH,
            output_root=args.output,
        )
    except (FFLogsError, ValueError, httpx.HTTPError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved source: {result.source}")
    print(f"Wrote {result.action_count} actions: {result.actions}")
    return 0
