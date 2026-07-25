from datetime import UTC, datetime
from decimal import Decimal

from app.domain.market_data import IntradayBar, validate_intraday_bars


def _bar(minute: int, o: str, h: str, low: str, c: str, vol: int = 1000) -> IntradayBar:
    return IntradayBar(
        symbol="TEST",
        ts=datetime(2026, 7, 24, 14, minute, tzinfo=UTC),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=vol,
    )


def test_clean_intraday_bars_all_valid() -> None:
    bars = [_bar(0, "10", "11", "9", "10.5"), _bar(15, "10.5", "12", "10", "11")]
    result = validate_intraday_bars("TEST", bars)
    assert len(result.valid) == 2
    assert result.rejected == []


def test_rejects_incoherent_rows() -> None:
    bars = [
        _bar(0, "10", "9", "11", "10"),  # high < low
        _bar(15, "10", "11", "9", "10"),  # ok
        _bar(30, "10", "11", "9", "10", vol=-5),  # negative volume
    ]
    result = validate_intraday_bars("TEST", bars)
    assert len(result.valid) == 1
    reasons = {reason for _, reason in result.rejected}
    assert reasons == {"high_below_low", "negative_volume"}


def test_sorts_by_timestamp() -> None:
    bars = [_bar(30, "10", "11", "9", "10"), _bar(0, "10", "11", "9", "10")]
    result = validate_intraday_bars("TEST", bars)
    assert [b.ts.minute for b in result.valid] == [0, 30]


def test_no_extreme_move_flagging_intraday() -> None:
    # A 60% jump between intraday bars is a legit gap/halt, not a split — must be kept.
    bars = [_bar(0, "10", "10", "10", "10"), _bar(15, "16", "16", "16", "16")]
    result = validate_intraday_bars("TEST", bars)
    assert len(result.valid) == 2
