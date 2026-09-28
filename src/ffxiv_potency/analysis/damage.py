"""Convert FF Logs overkill records into the portion of a hit that landed."""

from typing import Any


def landed_fraction(event: dict[str, Any]) -> float:
    """Return dealt damage / damage before overkill clipping."""
    amount = event.get("amount")
    overkill = event.get("overkill")
    if (
        isinstance(amount, (int, float))
        and amount > 0
        and isinstance(overkill, (int, float))
        and overkill > 0
    ):
        return amount / (amount + overkill)
    return 1.0
