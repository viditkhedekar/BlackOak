"""yfinance market-data adapter (no API key required).

Used for the price backfill and benchmark history. yfinance is convenient but
fragile — everything provider-specific stays inside this file so a swap to Alpaca
or FMP never touches services or the domain (ADR-0004).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import structlog
import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.domain.market_data import Bar

log = structlog.get_logger()


def _to_decimal(value: object) -> Decimal:
    # Go through str so we don't inherit binary-float artifacts in a money column.
    return Decimal(str(value))


class YFinanceMarketData:
    name = "yfinance"

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        # yfinance's ``end`` is exclusive; add a day so the range is inclusive.
        frame = yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=False,
            raise_errors=False,
        )
        if frame is None or frame.empty:
            log.info("yfinance.no_data", symbol=symbol, start=str(start), end=str(end))
            return []

        bars: list[Bar] = []
        for ts, row in frame.iterrows():
            close = _to_decimal(row["Close"])
            adj = _to_decimal(row["Adj Close"])
            # yfinance sometimes emits NaN adj_close on the most recent bar; the raw
            # OHLC is still good, so fall back to close rather than lose the row.
            if adj.is_nan():
                adj = close
            bars.append(
                Bar(
                    symbol=symbol,
                    date=ts.date(),
                    open=_to_decimal(row["Open"]),
                    high=_to_decimal(row["High"]),
                    low=_to_decimal(row["Low"]),
                    close=close,
                    adj_close=adj,
                    volume=int(row["Volume"]),
                )
            )
        return bars
