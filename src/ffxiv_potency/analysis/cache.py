"""Content-addressed, disposable JSON cache for per-player calculations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from importlib.resources import files
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from ..patches import LATEST_KNOWN_PATCH
from .config import action_data_root, reference_path
from .models import AnalysisResult

# Increment for changes to analysis semantics or the persisted result schema.
ANALYZER_REVISION = 12
CACHE_FILENAME = "analysis-cache.json"


def cache_root(logs_root: Path) -> Path:
    """Keep calculations next to, rather than inside, downloaded logs."""
    return logs_root.parent / "analysis-cache"


def cache_path(directory: Path) -> Path:
    """Locate a player cache for standard layouts or standalone saved logs."""
    if directory.name.startswith("source-") and directory.parent.name.startswith("fight-"):
        logs_root = directory.parents[2]
        return (cache_root(logs_root) / directory.parents[1].name
                / directory.parent.name / f"{directory.name}.json")
    identity = hashlib.sha256(directory.name.encode()).hexdigest()
    return cache_root(directory) / "local" / f"{identity}.json"


def _reference_roots() -> tuple[Path, Path]:
    return (Path(str(files("ffxiv_potency").joinpath("data"))),
            Path(__file__).resolve().parents[3] / "data")


def _input_bytes(name: str, path: Path) -> bytes:
    """Ignore capture provenance while retaining every calculation input."""
    payload = path.read_bytes()
    if path.suffix != ".json" or name.startswith("log/"):
        return payload
    try:
        document = json.loads(payload)
    except (UnicodeError, ValueError):
        return payload
    if isinstance(document, dict):
        if name == "actions" or path.name == "actions.json":
            document.pop("source", None)
        elif path.name == "datasets.json":
            document.pop("last_capture", None)
            for category in ("action_sets", "gear_sets", "pet_scaling_sets", "effect_sets"):
                for row in document.get(category, []):
                    if isinstance(row, dict):
                        row.pop("verified_through", None)
        elif path.name == "patches.json":
            document.pop("sources", None)
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def _fingerprint(directory: Path, actions_path: Path) -> str:
    inputs = {f"log/{path.name}": path for path in directory.glob("*.json")
              if path.name != CACHE_FILENAME}
    inputs["actions"] = actions_path
    # Hash effective reference files by logical name, regardless of installation path.
    for folder in ("jobs", "consumables", "encounters", "raid_effects"):
        for data_root in _reference_roots():
            for path in (data_root / folder).rglob("*.json"):
                inputs[f"reference/{path.relative_to(data_root).as_posix()}"] = path
    inputs["reference/patches.json"] = reference_path("patches.json")
    root = action_data_root(actions_path)
    for path in (root / "jobs").rglob("*.json"):
        inputs[f"reference/{path.relative_to(root).as_posix()}"] = path
    for folder in ("raid_effects", "raid_buffs"):
        for path in (root / folder).rglob("*.json"):
            inputs[f"override/{path.relative_to(root).as_posix()}"] = path
    package = Path(__file__).resolve().parents[1]
    sources = list((package / "analysis").rglob("*.py"))
    sources += [package / "fflogs/partitions.py", package / "patches.py",
                package / "jobguide/schema.py", package / "datasets.py", package / "reference_data.py", package / "raid_effects.py"]
    for path in sources:
        inputs[f"code/{path.relative_to(package).as_posix()}"] = path
    digest = hashlib.sha256(f"{ANALYZER_REVISION}:{LATEST_KNOWN_PATCH}".encode())
    for name, path in sorted(inputs.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(_input_bytes(name, path)).digest())
    return digest.hexdigest()


def _encode(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def _decode(value: Any, expected: Any) -> Any:
    origin = get_origin(expected)
    args = get_args(expected)
    if origin in (Union, UnionType):
        for option in args:
            try:
                return _decode(value, option)
            except (TypeError, ValueError):
                pass
        raise ValueError("invalid cached union value")
    if origin is tuple:
        if not isinstance(value, list):
            raise TypeError("cached tuple must be an array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(item, args[0]) for item in value)
        if len(value) != len(args):
            raise ValueError("invalid cached tuple length")
        return tuple(_decode(item, kind) for item, kind in zip(value, args, strict=True))
    if isinstance(expected, type) and is_dataclass(expected):
        if not isinstance(value, dict) or set(value) != {field.name for field in fields(expected)}:
            raise ValueError("invalid cached result fields")
        hints = get_type_hints(expected)
        return expected(**{name: _decode(item, hints[name]) for name, item in value.items()})
    if expected is float and type(value) in (int, float):
        return float(value)
    if type(value) is not expected:
        raise TypeError("invalid cached result type")
    return value


def cached_analysis(
    directory: Path, actions_path: Path,
    calculate: Callable[[Path, Path], AnalysisResult], *, gear: str | None = None,
) -> AnalysisResult:
    """Reuse an exact input match; cache failures never block analysis."""
    path = cache_path(directory)
    try:
        key = _fingerprint(directory, actions_path) + ":" + str(gear)
    except OSError:
        return calculate(directory, actions_path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["key"] == key and document["revision"] == ANALYZER_REVISION:
            result = _decode(document["result"], AnalysisResult)
            return result
    except (OSError, ValueError, TypeError, KeyError):
        pass
    result = calculate(directory, actions_path)
    temporary = None
    try:
        # Never publish a result if its inputs changed while calculating.
        if _fingerprint(directory, actions_path) + ":" + str(gear) != key:
            return result
        document = {"revision": ANALYZER_REVISION, "key": key, "result": _encode(result)}
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".analysis-", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, allow_nan=False)
        os.replace(temporary, path)
    except (OSError, ValueError):
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return result
