"""Map a UI range token (1M, 6M, 1Y, …) to a start date. Pure helper."""

from __future__ import annotations

from datetime import date, timedelta

_RANGE_DAYS: dict[str, int | None] = {
    "1M": 31,
    "3M": 92,
    "6M": 183,
    "1Y": 366,
    "2Y": 731,
    "5Y": 1827,
    "MAX": None,
}

VALID_RANGES = tuple(_RANGE_DAYS.keys())


def range_to_start(range_token: str, today: date) -> date | None:
    """Return the inclusive start date for a range, or None for MAX (no lower bound)."""
    days = _RANGE_DAYS.get(range_token.upper())
    if days is None:
        return None
    return today - timedelta(days=days)
