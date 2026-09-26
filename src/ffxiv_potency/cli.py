"""Command-line interface for FFXIV potency tools."""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Self

import httpx
from dotenv import load_dotenv

from .fflogs import (
    AnalysisResult,
    FFLogsError,
    analyze_saved_fight,
    download_report_events,
    parse_report_url,
    refresh_report_rankings,
    top_ranked_sources,
)
from .fflogs.reference import ReportReference
from .jobguide.raid_buffs import update_raid_effects
from .jobguide.snapshot import LATEST_KNOWN_PATCH, update_job_guide

SUPPORTED_JOBS = {"mch": "machinist", "machinist": "machinist"}
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

    jobguide = commands.add_parser("jobguide", help="work with official job-guide data")
    jobguide.add_argument("item", help="job name or abbreviation (MCH), or 'buffs'")
    jobguide.add_argument("--output", type=Path, default=Path("data"), help="output root")

    fflogs = commands.add_parser("fflogs", help="download one selected FF Logs fight")
    fflogs.add_argument("url", help="report URL, or job abbreviation such as MCH")
    fflogs.add_argument("fight", nargs="?", help="fight abbreviation such as m9s")
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
    return f"{minutes}m{remaining:02d}s"


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


def _print_analysis(result: AnalysisResult) -> None:
    print()
    print(f"Player: {result.source_name}")
    print(f"Fight: {_format_fight(result)}, {_format_duration(result.duration_seconds)}")
    print(f"nDPS: {result.ndps:,.1f}" if result.ndps is not None else "nDPS: n/a")
    print(f"rDPS: {result.rdps:,.1f}" if result.rdps is not None else "rDPS: n/a")
    print(f"Landed damage events: {result.landed_damage_events}")
    print(f"Matched potency events: {result.matched_damage_events}")
    print(f"Landed potency: {_format_potency(result.potency_min, result.potency_max)}")
    print(f"Potency per second: {_format_pps(result.pps_min, result.pps_max)}")
    if result.ghosted:
        print("\nGhosted damaging casts:")
        events = sorted((time, name) for name, times in result.ghosted_times for time in times)
        for time, name in events:
            print(f"  {_format_timestamp(time)} {name}")
    print("\nPotions:")
    print(f"  Uses: {result.potion.uses}")
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
    print(f"  Adjusted luck score: {result.adjusted_luck_score:.2%}")
    print("\nActions:")
    for action in result.actions:
        potency = _format_potency(action.potency_min, action.potency_max)
        uses = (
            f"{action.uses} {'use' if action.uses == 1 else 'uses'}, "
            if action.uses is not None
            else ""
        )
        hits = f"{action.hits} {'hit' if action.hits == 1 else 'hits'}"
        print(f"  {action.name}: {uses}{hits}, {potency} total potency")
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
    if result.pet_deployments:
        print("\nPet deployments:")
        for deployment in result.pet_deployments:
            missing = (
                f" (missing {' and '.join(deployment.missing_finishers)})"
                if deployment.missing_finishers
                else ""
            )
            print(
                f"  {_format_timestamp(deployment.timestamp_seconds)} {deployment.actor}: "
                f"{deployment.gauge_spent} {deployment.gauge}, "
                f"{_format_potency(deployment.potency_min, deployment.potency_max)} total potency{missing}"
            )
    if result.unmatched:
        print("\nUnmatched landed damage:")
        for name, count in result.unmatched:
            print(f"  {name}: {count}")
    print()


def _print_comparison(results: Sequence[AnalysisResult]) -> None:
    print()


def _compare_directories(
    directories: Sequence[Path], override: Path | None, progress: _Progress | None = None
) -> None:
    jobs = [_source_job(directory) for directory in directories]
    if len(set(jobs)) != 1:
        raise ValueError(f"comparison requires the same job; received: {', '.join(jobs)}")
    actions_path = _actions_for_job(jobs[0], override)
    results = []
    if progress is not None:
        progress.update("Calculating", 0, len(directories))
    for index, directory in enumerate(directories, 1):
        results.append(analyze_saved_fight(directory, actions_path))
        if progress is not None:
            progress.update("Calculating", index, len(directories))
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
    print(
        f"{'Player':<24} {'Duration':>9} {'rDPS':>10} {'nDPS':>10} "
        f"{'Potency':>12} {'PPS':>9} "
        f"{'Luck':>8} {'aLuck':>8}"
    )
    for result in results:
        potency = _format_potency(result.potency_min, result.potency_max)
        pps = _format_pps(result.pps_min, result.pps_max)
        duration = _format_duration(result.duration_seconds)
        ndps = f"{result.ndps:,.1f}" if result.ndps is not None else "n/a"
        rdps = f"{result.rdps:,.1f}" if result.rdps is not None else "n/a"
        print(
            f"{result.source_name[:24]:<24} {duration:>9} {rdps:>10} {ndps:>10} {potency:>12} "
            f"{pps:>9} {result.luck_score:>8.2%} {result.adjusted_luck_score:>8.2%}"
        )
    print()


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


def _actions_for_job(job: str, override: Path | None) -> Path:
    if job not in SUPPORTED_JOBS.values():
        raise ValueError(f"job {job!r} is not supported yet; currently only machinist is supported")
    path = override or Path("data") / job / LATEST_KNOWN_PATCH / "actions.json"
    _require_actions(path, job)
    return path


def _saved_directory(output: Path, reference: ReportReference) -> Path:
    return (
        output
        / reference.report_code
        / f"fight-{reference.fight_id}"
        / f"source-{reference.source_id}"
    )


def _reference_from_directory(directory: Path) -> ReportReference | None:
    """Recover an FF Logs reference from the downloader's canonical path."""
    fight_match = _FIGHT_DIRECTORY.fullmatch(directory.parent.name)
    source_match = _SOURCE_DIRECTORY.fullmatch(directory.name)
    report_code = directory.parent.parent.name
    if fight_match is None or source_match is None or not report_code.isalnum():
        return None
    return ReportReference(
        report_code=report_code,
        fight_id=int(fight_match.group(1)),
        source_id=int(source_match.group(1)),
    )


def _resolve_analysis_directory(source: str, output: Path, *, announce: bool = True) -> Path:
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
    urls: Sequence[str], output: Path, actions: Path | None, progress: _Progress
) -> None:
    # A source may appear more than once in a comparison; only one worker may
    # write its files, while the result still appears in each requested position.
    unique_urls = list(dict.fromkeys(urls))
    directories_by_url: dict[str, Path] = {}
    progress.update("Downloading", 0, len(urls))
    with ThreadPoolExecutor(max_workers=min(3, len(unique_urls))) as executor:
        pending = {
            executor.submit(_resolve_analysis_directory, url, output, announce=False): url
            for url in unique_urls
        }
        for finished in as_completed(pending):
            url = pending[finished]
            directories_by_url[url] = finished.result()
            completed = sum(url in directories_by_url for url in urls)
            progress.update("Downloading", completed, len(urls))
    directories = [directories_by_url[url] for url in urls]
    if progress.enabled:
        _compare_directories(directories, actions, progress)
    else:
        _compare_directories(directories, actions)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    try:
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
                    args.source, args.output, announce=not progress.enabled
                )
                progress.update("Downloading", 1, 1)
                actions_path = _actions_for_job(_source_job(directory), args.actions)
                progress.update("Calculating", 0, 1)
                result = analyze_saved_fight(directory, actions_path)
                progress.update("Calculating", 1, 1)
            _print_analysis(result)
            return 0

        if args.command == "fflogs":
            if args.fight is not None:
                job = SUPPORTED_JOBS.get(args.url.casefold())
                if job is None:
                    raise ValueError(
                        f"unsupported job {args.url!r}; currently only MCH is supported"
                    )
                encounter_id = CURRENT_FIGHTS.get(args.fight.casefold())
                if encounter_id is None:
                    raise ValueError(
                        f"unknown fight {args.fight!r}; choose: {', '.join(CURRENT_FIGHTS)}"
                    )
                with _Progress() as progress:
                    progress.message("Processing...")
                    references = top_ranked_sources(encounter_id, job)
                    urls = [
                        (
                            f"https://www.fflogs.com/reports/{reference.report_code}"
                            f"?fight={reference.fight_id}&source={reference.source_id}"
                        )
                        for reference in references
                    ]
                    _download_and_compare(urls, args.output, None, progress)
                return 0
            reference = parse_report_url(args.url)
            download = download_report_events(reference, args.output)
            print(f"Saved fight data: {download.directory}")
            print(f"Damage events: {download.damage_event_count}")
            print(f"Cast events: {download.cast_event_count}")
            return 0

        if args.item.casefold() == "buffs":
            output = update_raid_effects(args.output)
            print(f"Saved raid effects: {output}")
            return 0

        job = SUPPORTED_JOBS.get(args.item.casefold())
        if job is None:
            raise ValueError(f"unsupported job {args.item!r}; use 'machinist', 'MCH', or 'buffs'")
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
