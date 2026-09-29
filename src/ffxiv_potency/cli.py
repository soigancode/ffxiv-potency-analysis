"""Command-line interface for FFXIV potency tools."""

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Self

import httpx
from dotenv import load_dotenv

from .analysis import (
    AnalysisError,
    AnalysisResult,
    analyze_saved_fight,
)
from .analysis.config import reference_path
from .analysis.penalties import DamagePenaltySummary
from .fflogs import (
    FFLogsClient,
    FFLogsError,
    download_report_events,
    parse_report_url,
    refresh_report_rankings,
)
from .fflogs.download import (
    refresh_encounter_overkill_events,
    refresh_player_status_events,
    refresh_report_date,
    refresh_revival_buff_events,
    refresh_targetability_events,
)
from .fflogs.partitions import require_current_patch
from .fflogs.rankings import (
    accessible_ranked_sources,
    ranked_source,
    ranked_sources_in_range,
    validate_rank_range,
)
from .fflogs.reference import (
    ReportReference,
    report_code_from_directory,
    report_directory_name,
)
from .jobguide.raid_buffs import update_raid_effects
from .jobguide.snapshot import LATEST_KNOWN_PATCH, update_job_guide

SUPPORTED_JOBS = {
    "brd": "bard", "bard": "bard",
    "mch": "machinist", "machinist": "machinist",
}
CURRENT_FIGHTS = {
    "m9s": 101,
    "m10s": 102,
    "m11s": 103,
    "m12sp1": 104,
    "m12sp2": 105,
    "umad": 1085,
    "dmu": 1085,
}
_SAVED_FIGHT_FILES = ("fight.json", "master-data.json", "damage-events.json", "cast-events.json")
_FIGHT_DIRECTORY = re.compile(r"fight-(\d+)")
_SOURCE_DIRECTORY = re.compile(r"source-(\d+)")
_RANK_RANGE = re.compile(r"(\d+)-(\d+)")


class _Progress(AbstractContextManager["_Progress"]):
    """Show completed fights on one terminal line, then remove it."""

    def __init__(self) -> None:
        self.width = 0
        self.enabled = sys.stderr.isatty()

    def __enter__(self) -> Self:
        return self

    def update(self, label: str, done: int, total: int) -> None:
        if not self.enabled:
            return
        filled = round(20 * done / total)
        line = f"{label}: [{'#' * filled}{'-' * (20 - filled)}] {done}/{total}"
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
    jobguide.add_argument("item", nargs="?", help="job name or abbreviation (BRD/MCH), or 'buffs'")
    jobguide.add_argument("--output", type=Path, default=Path("data"), help="output root")

    clear = commands.add_parser("clear", help="remove downloaded data")
    clear.add_argument("item", choices=("logs",), help="data to remove")
    clear.add_argument("--output", type=Path, default=Path("data/logs"), help="logs directory")
    clear.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    fflogs = commands.add_parser("fflogs", help="download one selected FF Logs fight")
    fflogs.add_argument("url", help="'limit', a report URL, or a job such as BRD/MCH")
    fflogs.add_argument("fight", nargs="?", help="fight abbreviation such as m9s")
    fflogs.add_argument("rank", nargs="?", help="analyse one rank or compare an inclusive range, e.g. 5000-5500")
    fflogs.add_argument("--output", type=Path, default=Path("data/logs"), help="output root")

    compare = commands.add_parser("compare", help="download and compare FF Logs sources")
    compare.add_argument("urls", nargs="+", help="two to ten copied report URLs")
    compare.add_argument(
        "--actions", type=Path, help=f"override the job's default {LATEST_KNOWN_PATCH} actions.json"
    )
    compare.add_argument("--output", type=Path, default=Path("data/logs"), help="output root")

    analyse = commands.add_parser("analyse", help="download if needed and calculate potency")
    analyse.add_argument("source", help="saved source directory or copied FF Logs URL")
    analyse.add_argument(
        "--actions", type=Path, help=f"override the job's default {LATEST_KNOWN_PATCH} actions.json"
    )
    analyse.add_argument("--output", type=Path, default=Path("data/logs"), help="download root")
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
    return f"{result.fight_name}{suffix}"


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
    result: AnalysisResult, *, anonymous: bool = False, rank: int | None = None
) -> None:
    print()
    print(f"Player: {_display_player_name(result.source_name, anonymous=anonymous)}")
    if rank is not None:
        print(f"Rank: {rank}")
    wipe = " (wipe)" if result.kill is False else ""
    print(f"Fight: {_format_fight(result)}, {_format_duration(result.duration_seconds)}{wipe}")
    if result.food is not None:
        note = "" if result.food.recorded else " (configured; not identified in fight events)"
        print(f"Food: {result.food.name}{note}")
        for begin, finish in result.food_missing_windows:
            print(f"  Without food: {_format_timestamp(begin)}–{_format_timestamp(finish)}")
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
                f"  {window.name}: {_format_timestamp(window.start_seconds)}–"
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
                      f"{uncertain} uses with ambiguous potency")
                for use in estimate.apex_uses:
                    if len(use.plausible_gauges) == 1:
                        note = f"{use.gauge} gauge"
                    elif use.plausible_gauges:
                        low, high = use.plausible_gauges[0], use.plausible_gauges[-1]
                        note = f"best estimate {use.gauge} gauge (plausible {low}–{high} gauge)"
                    else:
                        note = f"best estimate {use.gauge} gauge (outside expected damage range)"
                    hits_label = "hit" if use.hits == 1 else "hits"
                    potency_label = (
                        f", {use.potency:,.0f} total potency"
                        if use.potency is not None else ""
                    )
                    print(f"    {_format_timestamp(use.seconds)}: {use.hits} {hits_label}, "
                          f"{note}{potency_label}")
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
                f"{hit.damage:,}/{hit.damage + hit.overkill:,} damage "
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
    print("\nPotions:")
    print(f"  Uses: {result.potion.uses}")
    if result.potion.uses and result.potion.item is not None:
        note = "" if result.potion.item.recorded else " (configured; not identified in fight events)"
        print(f"  Item: {result.potion.item.name}{note}")
    for index, window in enumerate(result.potion.windows, 1):
        if window.start_seconds is not None and window.end_seconds is not None:
            print(
                f"  Window {index}: {_format_timestamp(window.start_seconds)}–{_format_timestamp(window.end_seconds)}"
            )
        elif window.observed_start_seconds is not None and window.observed_end_seconds is not None:
            print(
                f"  Window {index}: start unknown; Medicated observed "
                f"{_format_timestamp(window.observed_start_seconds)}–{_format_timestamp(window.observed_end_seconds)}"
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
                f"  {started}–{ended}: {wildfire.landed_weaponskills}/6 landed weaponskills, "
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
                f"  {_format_timestamp(deployment.timestamp_seconds)} {deployment.actor}: "
                f"{deployment.gauge_spent} {deployment.gauge}, "
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


def _compare_directories(
    directories: Sequence[Path], override: Path | None, progress: _Progress | None = None,
    *, rank_positions: Sequence[int] | None = None, skip_analysis_errors: bool = False,
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
        progress.update("Calculating", 0, len(directories))
    for index, directory in enumerate(directories, 1):
        try:
            _verify_supported_fight(directory)
            result = analyze_saved_fight(directory, actions_path)
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
            progress.update("Calculating", index, len(directories))
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
    rank_header = f"{'Rank':>4} " if rank_positions is not None else ""
    print(
        f"{rank_header}{'Player':<24} {'Duration':>9} {'rDPS':>10} {'nDPS':>10} "
        f"{'Potency':>12} {'PPS':>9} "
        f"{'Luck':>8} {'aLuck':>8}"
    )
    for index, result in enumerate(results):
        potency = _format_potency(result.potency_min, result.potency_max)
        pps = _format_pps(result.pps_min, result.pps_max)
        duration = _format_duration(result.duration_seconds)
        ndps = f"{result.ndps:,.1f}" if result.ndps is not None else "n/a"
        rdps = f"{result.rdps:,.1f}" if result.rdps is not None else "n/a"
        rank = f"{compared_ranks[index]:>4} " if rank_positions is not None else ""
        player = _comparison_player_field(result.source_name, compared_directories[index])
        print(
            f"{rank}{player} {duration:>9} {rdps:>10} {ndps:>10} {potency:>12} "
            f"{pps:>9} {result.luck_score:>8.2%} {result.adjusted_luck_score:>8.2%}"
        )
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
        raise ValueError(f"job {job!r} is not supported yet; currently only Bard and Machinist are supported")
    path = override or Path("data") / job / LATEST_KNOWN_PATCH / "actions.json"
    if override is None and not path.is_file():
        path = reference_path(job, LATEST_KNOWN_PATCH, "actions.json")
    _require_actions(path, job)
    return path


def _saved_directory(output: Path, reference: ReportReference) -> Path:
    return (
        output
        / report_directory_name(reference.report_code)
        / f"fight-{reference.fight_id}"
        / f"source-{reference.source_id}"
    )


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
        rankings_path = directory / "rankings.json"
        try:
            cached_rankings = json.loads(rankings_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            cached_rankings = None
        if reference is not None and not (
            isinstance(cached_rankings, dict)
            and cached_rankings.get("metric") == "ndps"
            and "rdps" in cached_rankings
        ):
            refresh_report_rankings(reference, directory)
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


def _download_and_compare(
    urls: Sequence[str], output: Path, actions: Path | None, progress: _Progress,
    *, rank_positions: Sequence[int] | None = None, skip_analysis_errors: bool = False,
) -> tuple[tuple[int, str], ...]:
    # A source may appear more than once in a comparison; only one worker may
    # write its files, while the result still appears in each requested position.
    unique_urls = list(dict.fromkeys(urls))
    directories_by_url: dict[str, Path] = {}
    failures_by_url: dict[str, str] = {}
    progress.update("Downloading", 0, len(urls))
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
            progress.update("Downloading", completed, len(urls))
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
    if progress.enabled:
        if compared_ranks is None:
            _compare_directories(directories, actions, progress)
        elif skip_analysis_errors:
            return skipped + _compare_directories(
                directories, actions, progress, rank_positions=compared_ranks,
                skip_analysis_errors=True,
            )
        else:
            _compare_directories(directories, actions, progress, rank_positions=compared_ranks)
    else:
        if compared_ranks is None:
            _compare_directories(directories, actions)
        elif skip_analysis_errors:
            return skipped + _compare_directories(
                directories, actions, rank_positions=compared_ranks,
                skip_analysis_errors=True,
            )
        else:
            _compare_directories(directories, actions, rank_positions=compared_ranks)
    return ()


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    try:
        if args.command == "clear":
            directory = args.output
            if directory.is_symlink():
                raise ValueError(f"logs directory must not be a symbolic link: {directory}")
            if not directory.exists():
                print(f"No saved logs in {directory}.")
                return 0
            if not directory.is_dir():
                raise ValueError(f"logs path is not a directory: {directory}")
            if not args.yes:
                try:
                    answer = input(f"Delete all saved logs in {directory}? [y/N] ")
                except EOFError:
                    answer = ""
                if answer.strip().casefold() not in {"y", "yes"}:
                    print("Cancelled.")
                    return 0
            for item in directory.iterdir():
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            print(f"Cleared saved logs in {directory}.")
            return 0

        if args.command == "compare":
            if not 2 <= len(args.urls) <= 10:
                raise ValueError("compare requires two to ten FF Logs URLs")
            with _Progress() as progress:
                _download_and_compare(args.urls, args.output, args.actions, progress)
            return 0

        if args.command == "analyse":
            with _Progress() as progress:
                progress.update("Downloading", 0, 1)
                directory = _resolve_analysis_directory(
                    args.source, args.output, announce=not progress.enabled,
                    include_targetability=True,
                )
                progress.update("Downloading", 1, 1)
                job = _source_job(directory)
                actions_path = _actions_for_job(job, args.actions)
                _verify_supported_fight(directory)
                progress.update("Calculating", 0, 1)
                result = analyze_saved_fight(directory, actions_path)
                progress.update("Calculating", 1, 1)
            reference = _reference_from_directory(directory)
            _print_analysis(
                result,
                anonymous=reference is not None and reference.report_code.startswith("a:"),
            )
            return 0

        if args.command == "fflogs":
            if args.url.casefold() == "limit":
                if args.fight is not None or args.rank is not None:
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
                        f"unsupported job {args.url!r}; use BRD or MCH"
                    )
                encounter_id = CURRENT_FIGHTS.get(args.fight.casefold())
                if encounter_id is None:
                    raise ValueError(
                        f"unknown fight {args.fight!r}; choose: {', '.join(CURRENT_FIGHTS)}"
                    )
                rank_range = _RANK_RANGE.fullmatch(args.rank) if args.rank is not None else None
                if rank_range is not None:
                    first, last = map(int, rank_range.groups())
                    validate_rank_range(first, last)
                    with _Progress() as progress:
                        progress.message("Processing...")
                        ranked, skipped = ranked_sources_in_range(encounter_id, job, first, last)
                        urls = [
                            f"https://www.fflogs.com/reports/{reference.report_code}"
                            f"?fight={reference.fight_id}&source={reference.source_id}"
                            for _, reference in ranked
                        ]
                        analysis_skipped = _download_and_compare(
                            urls, args.output, None, progress,
                            rank_positions=tuple(rank for rank, _ in ranked),
                            skip_analysis_errors=True,
                        )
                    skipped_ranks = (*skipped, *analysis_skipped)
                    args.output.mkdir(parents=True, exist_ok=True)
                    manifest = args.output / f"ranks-{job}-{args.fight.casefold()}-{first}-{last}.json"
                    manifest.write_text(json.dumps({
                        "job": job,
                        "fight": args.fight.casefold(),
                        "encounter_id": encounter_id,
                        "first_rank": first,
                        "last_rank": last,
                        "reports": [
                            {"rank": rank, "report_code": ref.report_code,
                             "fight_id": ref.fight_id, "source_id": ref.source_id}
                            for rank, ref in ranked
                        ],
                        "skipped": [
                            {"rank": rank, "reason": reason}
                            for rank, reason in skipped_ranks
                        ],
                    }, indent=2) + "\n", encoding="utf-8")
                    if skipped_ranks:
                        print("Skipped ranks: " + ", ".join(
                            f"{rank} ({reason})" for rank, reason in skipped_ranks
                        ))
                        print()
                    return 0
                if args.rank is not None:
                    if not args.rank.isdecimal() or int(args.rank) < 1:
                        raise ValueError("rank must be a positive number")
                    rank = int(args.rank)
                    with _Progress() as progress:
                        progress.message("Processing...")
                        reference = ranked_source(encounter_id, job, rank)
                        url = (
                            f"https://www.fflogs.com/reports/{reference.report_code}"
                            f"?fight={reference.fight_id}&source={reference.source_id}"
                        )
                        progress.update("Downloading", 0, 1)
                        directory = _resolve_analysis_directory(
                            url, args.output, announce=not progress.enabled,
                            include_targetability=True,
                        )
                        progress.update("Downloading", 1, 1)
                        actions_path = _actions_for_job(job, None)
                        _verify_supported_fight(directory)
                        progress.update("Calculating", 0, 1)
                        result = analyze_saved_fight(directory, actions_path)
                        progress.update("Calculating", 1, 1)
                    _print_analysis(
                        result, rank=rank, anonymous=reference.report_code.startswith("a:"),
                    )
                    return 0
                with _Progress() as progress:
                    progress.message("Processing...")
                    ranked, skipped = accessible_ranked_sources(encounter_id, job)
                    urls = [
                        (
                            f"https://www.fflogs.com/reports/{reference.report_code}"
                            f"?fight={reference.fight_id}&source={reference.source_id}"
                        )
                        for _, reference in ranked
                    ]
                    _download_and_compare(
                        urls, args.output, None, progress,
                        rank_positions=tuple(rank for rank, _ in ranked),
                    )
                if skipped:
                    print("Skipped inaccessible ranks: " + ", ".join(
                        str(rank) for rank, _ in skipped
                    ))
                print()
                return 0
            if args.rank is not None:
                raise ValueError("a rank requires a job and fight abbreviation")
            reference = parse_report_url(args.url)
            download = download_report_events(reference, args.output)
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
            raise ValueError(f"unsupported job {args.item!r}; use BRD, MCH, or buffs")
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
