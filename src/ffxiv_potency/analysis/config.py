"""Locate versioned reference files in the checkout or installed package."""

from importlib.resources import files
from pathlib import Path


def reference_path(*parts: str) -> Path:
    """Return the project's data file, falling back to the installed wheel."""
    checkout = Path(__file__).resolve().parents[3] / "data"
    candidate = checkout.joinpath(*parts)
    if candidate.is_file():
        return candidate
    return Path(str(files("ffxiv_potency").joinpath("data", *parts)))
