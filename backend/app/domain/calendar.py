"""Trading-calendar helpers (XNYS). Thin wrapper so the rest of the app never
imports exchange_calendars directly and calendar logic stays testable."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import exchange_calendars as xcals


@lru_cache(maxsize=1)
def _xnys() -> xcals.ExchangeCalendar:
    return xcals.get_calendar("XNYS")


def is_trading_day(day: date) -> bool:
    return bool(_xnys().is_session(day.isoformat()))


def previous_trading_day(day: date) -> date:
    """Most recent session on or before ``day``."""
    ts = _xnys().date_to_session(day.isoformat(), direction="previous")
    result: date = ts.date()
    return result
