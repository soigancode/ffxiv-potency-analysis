"""Locate versioned reference files in the checkout or installed package."""

from importlib.resources import files
from pathlib import Path


def reference_path(*parts: str) -> Path:
    """Return the project's data file, falling back to the installed wheel."""
    checkout = Path(__file__).resolve().parents[2] / "data"
    candidate = checkout.joinpath(*parts)
    if candidate.is_file():
        return candidate
    return Path(str(files("ffxiv_potency").joinpath("data", *parts)))


def action_data_root(actions_path: Path) -> Path:
    """Locate shared overrides for new and legacy custom action snapshots."""
    root = actions_path.parent.parent.parent
    return root.parent if root.name == "jobs" else root
