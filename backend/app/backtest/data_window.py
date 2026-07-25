"""DataWindow — the no-lookahead seam (ADR-0008).

`BacktestData` is loaded once (full history). A `DataWindow` binds an as-of date and
exposes only data with timestamp <= that date: price series are sliced with bisect, and
fundamentals are withheld until 45 days after fiscal period end (point-in-time discipline
— yfinance is not PIT, so this lag is the honest approximation). The live engine (R4)
will implement the same interface over the live DB, so identical strategy code runs in
both worlds.

Forward estimates are intentionally omitted in backtests: yfinance exposes only today's
value, which would be lookahead if applied to a historical bar. The valuation family
renormalizes over its remaining metrics.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain.factors import FundamentalSnapshot
from app.domain.signals import SignalInputs

FUNDAMENTALS_LAG_DAYS = 45


@dataclass(frozen=True, slots=True)
class OHLC:
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SymbolSeries:
    dates: list[date]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]  # adjusted closes
    volumes: list[float]
    raw_closes: list[float]  # unadjusted, for execution pricing
    fundamentals: list[tuple[date, FundamentalSnapshot]] = field(default_factory=list)


@dataclass
class BacktestData:
    sectors: dict[str, str]
    series: dict[str, SymbolSeries]
    spy_dates: list[date]
    spy_closes: list[float]
    vix_dates: list[date]
    vix_values: list[float]
    t10y2y_dates: list[date]
    t10y2y_values: list[float]

    def trading_dates(self) -> list[date]:
        """The backtest calendar — SPY's session dates (the reference series)."""
        return self.spy_dates


def _slice_upto(dates: list[date], values: list[float], as_of: date) -> list[float]:
    cut = bisect_right(dates, as_of)
    return values[:cut]


def _scalar_upto(dates: list[date], values: list[float], as_of: date) -> float | None:
    cut = bisect_right(dates, as_of)
    return values[cut - 1] if cut > 0 else None


class DataWindow:
    def __init__(self, data: BacktestData, as_of: date) -> None:
        self._data = data
        self.as_of = as_of

    def has_bar(self, symbol: str) -> bool:
        s = self._data.series.get(symbol)
        if s is None:
            return False
        i = bisect_right(s.dates, self.as_of) - 1
        return i >= 0 and s.dates[i] == self.as_of

    def bar(self, symbol: str) -> OHLC | None:
        """The exact as-of session's OHLC (unadjusted), or None if the symbol didn't
        trade that day. Execution uses these raw prices."""
        s = self._data.series.get(symbol)
        if s is None:
            return None
        i = bisect_right(s.dates, self.as_of) - 1
        if i < 0 or s.dates[i] != self.as_of:
            return None
        return OHLC(
            open=s.opens[i], high=s.highs[i], low=s.lows[i],
            close=s.raw_closes[i], volume=s.volumes[i],
        )

    def _visible_fundamentals(self, s: SymbolSeries) -> list[FundamentalSnapshot]:
        cutoff = self.as_of - timedelta(days=FUNDAMENTALS_LAG_DAYS)
        return [snap for fdate, snap in s.fundamentals if fdate <= cutoff]

    def signal_inputs(self, symbol: str) -> SignalInputs | None:
        s = self._data.series.get(symbol)
        if s is None:
            return None
        closes = _slice_upto(s.dates, s.closes, self.as_of)
        if not closes:
            return None
        return SignalInputs(
            symbol=symbol,
            sector=self._data.sectors.get(symbol, "Unknown"),
            closes=closes,
            highs=_slice_upto(s.dates, s.highs, self.as_of),
            lows=_slice_upto(s.dates, s.lows, self.as_of),
            volumes=_slice_upto(s.dates, s.volumes, self.as_of),
            opens=_slice_upto(s.dates, s.opens, self.as_of),
            current_price=closes[-1],
            market_closes=self.spy_closes(),
            annual=self._visible_fundamentals(s),
            estimates=None,  # omitted in backtest — see module docstring
        )

    def spy_closes(self) -> list[float]:
        return _slice_upto(self._data.spy_dates, self._data.spy_closes, self.as_of)

    def vix_series(self) -> list[float]:
        return _slice_upto(self._data.vix_dates, self._data.vix_values, self.as_of)

    def t10y2y(self) -> float | None:
        return _scalar_upto(self._data.t10y2y_dates, self._data.t10y2y_values, self.as_of)
