"""Next-cycle computation — what the dashboard counts down to.

The countdown is only honest if it lands on a time the worker will actually wake: inside
the RTH window, and never on a market holiday (cron alone would fire on those, since they
are weekdays).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.calendar import is_trading_day
from app.services.schedule import ET, minute_expr, next_cycle_at


def _et(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


@pytest.mark.parametrize(
    ("interval", "expected"),
    [(60, "0"), (30, "0,30"), (20, "0,20,40"), (15, "0,15,30,45")],
)
def test_minute_expr_builds_cron_field(interval: int, expected: str) -> None:
    assert minute_expr(interval) == expected


@pytest.mark.parametrize("bad", [0, 7, 45, 61, -5])
def test_minute_expr_rejects_intervals_that_do_not_divide_the_hour(bad: int) -> None:
    """A cadence like 45 min would silently produce an uneven cron field."""
    with pytest.raises(ValueError, match="divide 60 evenly"):
        minute_expr(bad)


def test_before_the_open_waits_for_the_first_cycle_of_the_day() -> None:
    # Thursday 07:00 ET, well before the 10:00 first cycle.
    assert next_cycle_at(60, _et(2026, 8, 13, 7)) == _et(2026, 8, 13, 10)


def test_midsession_rolls_to_the_next_hour() -> None:
    assert next_cycle_at(60, _et(2026, 8, 13, 11, 39)) == _et(2026, 8, 13, 12)


def test_after_the_last_cycle_rolls_to_the_next_trading_day() -> None:
    # 15:00 is the last cycle; 15:30 Thursday therefore means Friday 10:00.
    assert next_cycle_at(60, _et(2026, 8, 13, 15, 30)) == _et(2026, 8, 14, 10)


def test_friday_evening_skips_the_weekend() -> None:
    assert next_cycle_at(60, _et(2026, 8, 14, 18)) == _et(2026, 8, 17, 10)


def test_skips_a_market_holiday_that_falls_on_a_weekday() -> None:
    """Christmas 2026 is a Friday — cron would fire, the market is shut."""
    assert not is_trading_day(_et(2026, 12, 25, 10).date())
    # Thursday 24th after the close -> Monday 28th, not Friday the 25th.
    assert next_cycle_at(60, _et(2026, 12, 24, 16)) == _et(2026, 12, 28, 10)


def test_skips_thanksgiving() -> None:
    assert not is_trading_day(_et(2026, 11, 26, 10).date())
    assert next_cycle_at(60, _et(2026, 11, 25, 16)) == _et(2026, 11, 27, 10)


def test_half_hour_cadence_lands_on_the_half_hour() -> None:
    assert next_cycle_at(30, _et(2026, 8, 13, 11, 5)) == _et(2026, 8, 13, 11, 30)


@pytest.mark.parametrize(
    "start",
    [
        _et(2026, 8, 13, 3),
        _et(2026, 8, 15, 12),  # Saturday
        _et(2026, 12, 25, 11),  # holiday
        _et(2026, 7, 3, 9),  # holiday
        _et(2026, 1, 1, 10),  # holiday
    ],
)
def test_result_is_always_a_session_inside_the_cycle_window(start: datetime) -> None:
    fire = next_cycle_at(60, start)
    assert fire is not None
    assert fire > start
    assert is_trading_day(fire.date())
    assert 10 <= fire.astimezone(ET).hour <= 15
