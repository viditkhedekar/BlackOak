"""Seed the investable universe from the bundled S&P 500 constituent list."""

from __future__ import annotations

import csv
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.services.job_tracking import track_job

log = structlog.get_logger()

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "sp500.csv"

# SPY + equal-weight RSP + the 11 GICS sector SPDRs. Stored as companies rows with
# universe='ETF' so the intraday/signal pipeline covers them for free; the `sector`
# on each sector ETF is the GICS sector it tracks, which the R2 regime engine reads
# to tilt sector caps (sector ETF vs its own 50DMA).
_ETF_ROWS: list[dict[str, object]] = [
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "sector": None},
    {"symbol": "RSP", "name": "Invesco S&P 500 Equal Weight ETF", "sector": None},
    {"symbol": "XLK", "name": "Technology Select Sector SPDR", "sector": "Information Technology"},
    {"symbol": "XLV", "name": "Health Care Select Sector SPDR", "sector": "Health Care"},
    {"symbol": "XLF", "name": "Financial Select Sector SPDR", "sector": "Financials"},
    {"symbol": "XLY", "name": "Consumer Discretionary Select Sector SPDR", "sector": "Consumer Discretionary"},  # noqa: E501
    {"symbol": "XLC", "name": "Communication Services Select Sector SPDR", "sector": "Communication Services"},  # noqa: E501
    {"symbol": "XLI", "name": "Industrial Select Sector SPDR", "sector": "Industrials"},
    {"symbol": "XLP", "name": "Consumer Staples Select Sector SPDR", "sector": "Consumer Staples"},
    {"symbol": "XLE", "name": "Energy Select Sector SPDR", "sector": "Energy"},
    {"symbol": "XLU", "name": "Utilities Select Sector SPDR", "sector": "Utilities"},
    {"symbol": "XLRE", "name": "Real Estate Select Sector SPDR", "sector": "Real Estate"},
    {"symbol": "XLB", "name": "Materials Select Sector SPDR", "sector": "Materials"},
]


def load_seed_rows(path: Path = _SEED_PATH) -> list[dict[str, object]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return [
            {
                "symbol": row["symbol"].strip().upper(),
                "name": row["name"].strip(),
                "sector": row["sector"].strip() or None,
                "industry": row["industry"].strip() or None,
                "universe": "SP500",
                "is_active": True,
            }
            for row in reader
        ]


async def seed_universe(session: AsyncSession) -> int:
    """Upsert the S&P 500 universe. Idempotent — safe to re-run on constituent changes."""
    async with track_job(session, "seed_universe") as ctx:
        rows = load_seed_rows()
        repo = CompanyRepository(session)
        count = await repo.upsert_many(rows)
        ctx.records_processed = count
        ctx.meta = {"universe": "SP500", "symbols": count}
        return count


async def seed_etfs(session: AsyncSession) -> int:
    """Upsert SPY/RSP/sector-ETF rows into the ETF universe. Idempotent."""
    rows = [
        {**row, "industry": None, "universe": "ETF", "is_active": True} for row in _ETF_ROWS
    ]
    count = await CompanyRepository(session).upsert_many(rows)
    log.info("universe.seed_etfs", count=count)
    return count
