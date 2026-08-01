"""Alpaca market-data adapter (free IEX feed bundled with the paper account).

Alternative price source to yfinance behind the same MarketDataProvider port
(ADR-0004). Requires the paper API keys; read-only market data, no trading here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import structlog
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.domain.market_data import Bar, IntradayBar

# Intraday intervals the strategy engine understands, mapped to Alpaca timeframes.
_INTRADAY_TIMEFRAMES = {
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "30Min": TimeFrame(30, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
}

log = structlog.get_logger()


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


# Class shares: our universe stores them Yahoo-style (BRK-B, BF-B) because that is what
# the price feed seeds them from; Alpaca spells them with a dot (BRK.B) and rejects the
# hyphen outright. A single bad ticker fails the whole batched request, so translate at
# the adapter boundary and translate the response keys back to our canonical form.
def _to_alpaca(symbol: str) -> str:
    return symbol.replace("-", ".")


def _from_alpaca(symbol: str) -> str:
    return symbol.replace(".", "-")


class AlpacaMarketData:
    name = "alpaca"

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = StockHistoricalDataClient(api_key, secret_key)

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        request = StockBarsRequest(
            symbol_or_symbols=_to_alpaca(symbol),
            timeframe=TimeFrame.Day,
            start=datetime.combine(start, time.min, tzinfo=UTC),
            end=datetime.combine(end, time.max, tzinfo=UTC),
            feed=DataFeed.IEX,
        )
        barset = self._client.get_stock_bars(request)
        # get_stock_bars returns a BarSet whose .data maps symbol -> list[Bar].
        rows = barset.data.get(_to_alpaca(symbol), [])  # type: ignore[union-attr]
        if not rows:
            log.info("alpaca.no_data", symbol=symbol, start=str(start), end=str(end))
            return []

        # Alpaca does not provide an adjusted close on the IEX daily feed; use close.
        return [
            Bar(
                symbol=symbol,
                date=row.timestamp.date(),
                open=_to_decimal(row.open),
                high=_to_decimal(row.high),
                low=_to_decimal(row.low),
                close=_to_decimal(row.close),
                adj_close=_to_decimal(row.close),
                volume=int(row.volume),
            )
            for row in rows
        ]

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def fetch_intraday_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str = "15Min"
    ) -> dict[str, list[IntradayBar]]:
        """Batched intraday bars — one request covers the whole symbol list, which is
        what keeps 503 tickers inside the free-tier rate limit."""
        timeframe = _INTRADAY_TIMEFRAMES.get(interval)
        if timeframe is None:
            raise ValueError(f"Unsupported intraday interval: {interval}")

        request = StockBarsRequest(
            symbol_or_symbols=[_to_alpaca(s) for s in symbols],
            timeframe=timeframe,
            start=start,
            end=end,
            feed=DataFeed.IEX,
        )
        barset = self._client.get_stock_bars(request)
        data = barset.data  # type: ignore[union-attr]
        return {
            _from_alpaca(symbol): [
                IntradayBar(
                    symbol=_from_alpaca(symbol),
                    ts=row.timestamp,
                    open=_to_decimal(row.open),
                    high=_to_decimal(row.high),
                    low=_to_decimal(row.low),
                    close=_to_decimal(row.close),
                    volume=int(row.volume),
                )
                for row in rows
            ]
            for symbol, rows in data.items()
        }
