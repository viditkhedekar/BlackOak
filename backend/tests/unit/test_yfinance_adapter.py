"""Adapter transformation is tested against a fake yf.Ticker — no network.

We assert the DataFrame → Bar mapping and the NaN adj_close fallback, which is the
provider-specific logic worth locking down.
"""

from datetime import date
from decimal import Decimal

import pandas as pd

from app.adapters import yfinance_data
from app.adapters.yfinance_data import YFinanceMarketData


class _FakeTicker:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def history(self, **_: object) -> pd.DataFrame:
        return self._frame


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    idx = pd.to_datetime([r["date"] for r in rows])
    return pd.DataFrame(
        {
            "Open": [r["open"] for r in rows],
            "High": [r["high"] for r in rows],
            "Low": [r["low"] for r in rows],
            "Close": [r["close"] for r in rows],
            "Adj Close": [r["adj"] for r in rows],
            "Volume": [r["vol"] for r in rows],
        },
        index=idx,
    )


def test_maps_rows_to_bars(monkeypatch) -> None:
    frame = _frame(
        [{"date": "2026-01-02", "open": 10.0, "high": 11.0, "low": 9.5,
          "close": 10.5, "adj": 10.4, "vol": 1000}]
    )
    monkeypatch.setattr(yfinance_data.yf, "Ticker", lambda _s: _FakeTicker(frame))

    bars = YFinanceMarketData().fetch_daily_bars("AAPL", date(2026, 1, 1), date(2026, 1, 3))

    assert len(bars) == 1
    bar = bars[0]
    assert bar.date == date(2026, 1, 2)
    assert bar.close == Decimal("10.5")
    assert bar.adj_close == Decimal("10.4")
    assert isinstance(bar.open, Decimal)


def test_nan_adj_close_falls_back_to_close(monkeypatch) -> None:
    frame = _frame(
        [{"date": "2026-01-02", "open": 10.0, "high": 11.0, "low": 9.5,
          "close": 10.5, "adj": float("nan"), "vol": 1000}]
    )
    monkeypatch.setattr(yfinance_data.yf, "Ticker", lambda _s: _FakeTicker(frame))

    bars = YFinanceMarketData().fetch_daily_bars("AAPL", date(2026, 1, 1), date(2026, 1, 3))

    assert bars[0].adj_close == Decimal("10.5")  # fell back to close


def test_empty_frame_returns_no_bars(monkeypatch) -> None:
    monkeypatch.setattr(yfinance_data.yf, "Ticker", lambda _s: _FakeTicker(pd.DataFrame()))
    bars = YFinanceMarketData().fetch_daily_bars("AAPL", date(2026, 1, 1), date(2026, 1, 3))
    assert bars == []
