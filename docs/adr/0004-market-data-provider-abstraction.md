# ADR-0004: Market data behind a provider port (Alpaca + yfinance, FMP upgrade path)

**Status:** Accepted · 2026-07-25

## Context
No single free data source covers prices, fundamentals, and news well. Free sources (especially yfinance) can break or rate-limit without notice. Data access is the platform's biggest external risk.

## Decision
All market data flows through a `MarketDataProvider` Protocol. v1 adapters:
- **Alpaca Market Data** (free IEX feed bundled with the paper account) — OHLCV bars and quotes
- **yfinance** — fundamentals and benchmark history
- **Financial Modeling Prep** — adapter stubbed as the paid upgrade path for cleaner fundamentals/news

Postgres owns all data after ingest; API reads never hit providers directly.

## Consequences
- Swapping or adding a provider is a one-adapter change; domain and services never know the source.
- Every row carries a `source` column, so mixed-provider data stays auditable.
- yfinance fragility is contained: quarantine + job_runs alerting catches silent schema drift, and FMP is a drop-in replacement.
