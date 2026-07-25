"""Select the active market-data provider from configuration.

Services depend on the MarketDataProvider port, never on a concrete adapter; this
factory is the one place that knows which implementation is wired in (ADR-0004).
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.ports import (
    FundamentalsProvider,
    IntradayBarsProvider,
    MacroDataProvider,
    MarketDataProvider,
)


def get_market_data_provider(settings: Settings) -> MarketDataProvider:
    if settings.market_data_provider == "alpaca":
        from app.adapters.alpaca_market_data import AlpacaMarketData

        return AlpacaMarketData(settings.alpaca_api_key, settings.alpaca_secret_key)

    from app.adapters.yfinance_data import YFinanceMarketData

    return YFinanceMarketData()


def get_intraday_provider(settings: Settings) -> IntradayBarsProvider:
    # Intraday bars come from Alpaca's IEX feed — yfinance intraday is unreliable.
    from app.adapters.alpaca_market_data import AlpacaMarketData

    return AlpacaMarketData(settings.alpaca_api_key, settings.alpaca_secret_key)


def get_macro_provider(settings: Settings) -> MacroDataProvider:
    from app.adapters.fred_macro import FredMacro

    return FredMacro()


def get_fundamentals_provider(settings: Settings) -> FundamentalsProvider:
    # yfinance is the only free fundamentals source today; FMP is the paid upgrade path.
    from app.adapters.yfinance_fundamentals import YFinanceFundamentals

    return YFinanceFundamentals()
