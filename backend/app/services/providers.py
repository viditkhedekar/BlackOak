"""Select the active market-data provider from configuration.

Services depend on the MarketDataProvider port, never on a concrete adapter; this
factory is the one place that knows which implementation is wired in (ADR-0004).
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.ports import MarketDataProvider


def get_market_data_provider(settings: Settings) -> MarketDataProvider:
    if settings.market_data_provider == "alpaca":
        from app.adapters.alpaca_market_data import AlpacaMarketData

        return AlpacaMarketData(settings.alpaca_api_key, settings.alpaca_secret_key)

    from app.adapters.yfinance_data import YFinanceMarketData

    return YFinanceMarketData()
