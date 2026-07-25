from datetime import date

from app.domain.calendar import is_trading_day, previous_trading_day


def test_weekend_is_not_trading_day() -> None:
    assert is_trading_day(date(2026, 7, 25)) is False  # Saturday
    assert is_trading_day(date(2026, 7, 26)) is False  # Sunday


def test_weekday_is_trading_day() -> None:
    assert is_trading_day(date(2026, 7, 24)) is True  # Friday


def test_new_years_day_is_holiday() -> None:
    assert is_trading_day(date(2026, 1, 1)) is False


def test_previous_trading_day_rolls_back_over_weekend() -> None:
    assert previous_trading_day(date(2026, 7, 25)) == date(2026, 7, 24)
