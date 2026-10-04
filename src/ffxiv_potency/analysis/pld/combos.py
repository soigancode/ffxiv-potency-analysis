"""Paladin combo diagnostics using shared damage evidence."""

from ..combos import ComboInference as PldComboInference
from ..combos import ComboLoss as PldComboLoss
from ..combos import ComboSummary as PldComboSummary
from ..combos import combo_potencies, summarize_combos
from ..combos import infer_combos as _infer_combos

__all__ = [
    "PldComboInference",
    "PldComboLoss",
    "PldComboSummary",
    "combo_potencies",
    "infer_combos",
    "summarize_combos",
]


def infer_combos(damage, actions, names, source, start, profile, food_missing=()):
    return _infer_combos(damage, actions, names, source, start, profile, food_missing,
                         fixed={"Fast Blade", "Total Eclipse", "Shield Lob", "Shield Bash",
                                "Goring Blade", "Atonement", "Supplication", "Sepulchre"})
