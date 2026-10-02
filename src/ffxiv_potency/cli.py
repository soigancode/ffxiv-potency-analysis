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
ENCOUNTER_NAMES = {
    101: "Vamp Fatale",
    102: "Red Hot and Deep Blue",
    103: "The Tyrant",
    104: "Lindwurm",
    105: "Lindwurm II",
    1085: "Dancing Mad",
    1083: "Doomtrain",
    1084: "Enuo",
    4550: "Another Merchant's Tale",
    4549: "Mistwake",
    4551: "The Clyteum",
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
    shorthand = next((alias for alias, encounter in CURRENT_FIGHTS.items()
                      if encounter == result.encounter_id), None)
    suffix = f" ({shorthand})" if shorthand else ""
    name = ENCOUNTER_NAMES.get(result.encounter_id or 0, result.fight_name)
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
    from .reporting import print_analysis

    print_analysis(result, directory=directory, anonymous=anonymous, rank=rank)


def _format_pps_delta(result: AnalysisResult, baseline: AnalysisResult, index: int) -> str:
    if index == 0:
        return "-"
    if baseline.pps_min <= 0 or baseline.pps_max <= 0:
        return "n/a"
    low = 100 * (result.pps_min / baseline.pps_max - 1)
    high = 100 * (result.pps_max / baseline.pps_min - 1)
    return f"{low:+.2f}%" if abs(high-low) < 0.005 else f"{low:+.2f}% to {high:+.2f}%"


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
    from .reporting import issue_notes

    baseline_index = min(range(len(compared_ranks)), key=lambda i: compared_ranks[i]) if rank_positions is not None else 0
    delta_labels = ("dPPS",)
    hit_labels = ("HB", "Luck") if use_dps else ("aHB", "aLuck")
    labels = ("Duration", "Targetable", *dps_labels,
              "Potency", "PPS", *delta_labels, *hit_labels, "Notes",
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
            _format_pps_delta(result, results[baseline_index], 0 if index == baseline_index else 1),
            marker + f"{(result.hit_bonus if use_dps else result.adjusted_hit_bonus):+.2%}",
            marker + f"{(result.luck_score if use_dps else result.adjusted_luck_score):.2%}",
            issue_notes(result),
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
    if any(issue_notes(result) != "-" for result in results):
        print("Notes: KO deaths | DD Damage Down | G confirmed target death/untargetability ghosts")
    if any(deployment.gauge_assumed for result in results
           for deployment in result.pet_deployments):
        print("~ Potency, PPS, hit bonus, and luck include an unconfirmed 100 Battery Gauge carry-over.")
    if any(deployment.mch_gauge_inferred for result in results
           for deployment in result.pet_deployments):
        print("~ Potency, PPS, hit bonus, and luck include Battery estimated from Queen damage.")
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
    name = ENCOUNTER_NAMES.get(fight.encounter_id, fight.name)
    return f"{name} (fight {fight.id}{duration}){wipe}"


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
