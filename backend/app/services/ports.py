"""Ports (interfaces) that services depend on. Adapters implement these.

Keeping these as Protocols means services never import a concrete adapter, and every
port can be swapped for a fake in tests (docs/ARCHITECTURE.md, module rule 2).
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from app.domain.fundamentals import FundamentalRecord
from app.domain.market_data import Bar


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
class FundamentalsProvider(Protocol):
    """Source of annual statement snapshots. Implementations: yfinance, (future) FMP."""

    name: str

    def fetch_annual_fundamentals(self, symbol: str) -> list[FundamentalRecord]:
        """Return annual fundamentals (ascending by fiscal_date). Empty list if none."""
        ...
