from datetime import date
from decimal import Decimal

from app.domain.market_data import Bar, validate_bars


def _bar(
    day: int, o: str, h: str, low: str, c: str, adj: str | None = None, vol: int = 1000
) -> Bar:
    return Bar(
        symbol="TEST",
        date=date(2026, 1, day),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        adj_close=Decimal(adj if adj is not None else c),
        volume=vol,
    )


def test_clean_bars_all_valid() -> None:
    bars = [_bar(2, "10", "11", "9", "10.5"), _bar(3, "10.5", "12", "10", "11")]
    result = validate_bars("TEST", bars)
    assert len(result.valid) == 2
    assert not result.rejected
    assert not result.flagged


def test_rejects_high_below_low() -> None:
    result = validate_bars("TEST", [_bar(2, "10", "8", "9", "9.5")])
    assert not result.valid
    assert result.rejected[0][1] == "high_below_low"


def test_rejects_close_outside_range() -> None:
    result = validate_bars("TEST", [_bar(2, "10", "11", "9", "12")])
    assert result.rejected[0][1] == "close_outside_range"


def test_rejects_non_positive_price() -> None:
    result = validate_bars("TEST", [_bar(2, "0", "1", "0", "0.5")])
    assert result.rejected[0][1] == "non_positive_price"


def test_rejects_negative_volume() -> None:
    result = validate_bars("TEST", [_bar(2, "10", "11", "9", "10", vol=-5)])
    assert result.rejected[0][1] == "negative_volume"


def test_rejects_nan_without_raising() -> None:
    nan_bar = Bar("TEST", date(2026, 1, 2), Decimal("10"), Decimal("11"), Decimal("9"),
                  Decimal("10"), Decimal("NaN"), 1000)
    result = validate_bars("TEST", [nan_bar])
    assert result.rejected[0][1] == "nan_value"


def test_flags_extreme_move_but_keeps_row() -> None:
    bars = [_bar(2, "10", "10", "10", "10"), _bar(3, "16", "16", "16", "16")]  # +60%
    result = validate_bars("TEST", bars)
    assert len(result.valid) == 2  # kept
    assert result.flagged and result.flagged[0][1].startswith("extreme_move")


def test_orders_bars_chronologically_for_move_check() -> None:
    # Passed out of order; the extreme move is still detected against the prior session.
    bars = [_bar(3, "16", "16", "16", "16"), _bar(2, "10", "10", "10", "10")]
    result = validate_bars("TEST", bars)
    assert [b.date.day for b in result.valid] == [2, 3]
    assert result.flagged
