"""Ports (interfaces) that services depend on. Adapters implement these.

Keeping these as Protocols means services never import a concrete adapter, and every
port can be swapped for a fake in tests (docs/ARCHITECTURE.md, module rule 2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from app.domain.broker import (
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    PortfolioHistoryPoint,
)
from app.domain.fundamentals import EstimateRecord, FundamentalRecord
from app.domain.macro import MacroPoint
from app.domain.market_data import Bar, IntradayBar


@runtime_checkable
class MarketDataProvider(Protocol):
    """Source of daily OHLCV bars. Implementations: yfinance, Alpaca, (future) FMP."""

    name: str

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Return daily bars for ``symbol`` in [start, end].

        Raises on transport errors so the caller's retry/isolation logic can act;
        returns an empty list when the symbol legitimately has no data in range.
        """
        ...


@runtime_checkable
class IntradayBarsProvider(Protocol):
    """Source of intraday OHLCV bars, batched by design — one call covers many
    symbols so 503 tickers stay inside provider rate limits. Implementation: Alpaca."""

    name: str

    def fetch_intraday_bars(
        self, symbols: list[str], start: datetime, end: datetime, interval: str = "15Min"
    ) -> dict[str, list[IntradayBar]]:
        """Return {symbol: bars} for [start, end]. Symbols with no data are absent
        or map to an empty list; raises only on transport errors."""
        ...


@runtime_checkable
class MacroDataProvider(Protocol):
    """Source of macro time series (rates, curve, inflation). Implementation: FRED."""

    name: str

    def fetch_series(self, series_id: str, start: date, end: date) -> list[MacroPoint]:
        """Return observations ascending by date. Empty list if none."""
        ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    """Source of annual statement snapshots. Implementations: yfinance, (future) FMP."""

    name: str

    def fetch_annual_fundamentals(self, symbol: str) -> list[FundamentalRecord]:
        """Return annual fundamentals (ascending by fiscal_date). Empty list if none."""
        ...

    def fetch_estimates(self, symbol: str) -> EstimateRecord | None:
        """Return current forward estimates, or None if unavailable."""
        ...


@runtime_checkable
class BrokerClient(Protocol):
    """Paper broker. The DB owns order intent; the broker owns fills/positions (truth).
    Implementations: Alpaca paper, FakeBroker (tests). All methods are synchronous and
    called via asyncio.to_thread, matching the other adapters."""

    name: str

    def get_account(self) -> BrokerAccount: ...

    def list_positions(self) -> list[BrokerPosition]: ...

    def submit_order(
        self, client_order_id: str, symbol: str, side: str, qty: float
    ) -> BrokerOrder:
        """Submit a market order. ``client_order_id`` is our UUID — resubmitting the same
        id must return the existing order, never create a second (idempotency)."""
        ...

    def get_order(self, client_order_id: str) -> BrokerOrder | None:
        """Look up an order by our client id, or None if the broker has no record."""
        ...

    def get_portfolio_history(
        self, period: str = "1M", timeframe: str = "1H"
    ) -> list[PortfolioHistoryPoint]:
        """Equity marks the broker recorded for this account, oldest first.

        Used to seed the equity curve over stretches where nothing of ours was running.
        Empty list if the broker keeps no such history.
        """
        ...
