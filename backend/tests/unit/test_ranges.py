from datetime import date

from app.domain.ranges import VALID_RANGES, range_to_start


def test_max_has_no_lower_bound() -> None:
    assert range_to_start("MAX", date(2026, 7, 25)) is None


def test_one_year_lookback() -> None:
    start = range_to_start("1Y", date(2026, 7, 25))
    assert start == date(2025, 7, 24)


def test_case_insensitive() -> None:
    assert range_to_start("1y", date(2026, 7, 25)) == range_to_start("1Y", date(2026, 7, 25))


def test_all_declared_ranges_resolve() -> None:
    for token in VALID_RANGES:
        # Should not raise; MAX returns None, others a date.
        range_to_start(token, date(2026, 7, 25))
