"""Seed and ingest benchmark reference series (SPY today; sector ETFs later)."""

from __future__ import annotations

import asyncio
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.benchmarks import BenchmarkRepository
from app.domain.market_data import validate_bars
from app.services.job_tracking import track_job
from app.services.ports import MarketDataProvider

log = structlog.get_logger()

DEFAULT_BENCHMARKS = [("SPY", "SPDR S&P 500 ETF Trust")]


async def seed_benchmarks(session: AsyncSession) -> int:
    repo = BenchmarkRepository(session)
    for symbol, name in DEFAULT_BENCHMARKS:
        await repo.upsert(symbol, name)
    await session.commit()
    return len(DEFAULT_BENCHMARKS)


async def ingest_benchmarks(
    session: AsyncSession, provider: MarketDataProvider, start: date, end: date
) -> int:
    async with track_job(session, "ingest_benchmarks") as ctx:
        repo = BenchmarkRepository(session)
        written = 0
        for symbol, name in DEFAULT_BENCHMARKS:
            benchmark_id = await repo.upsert(symbol, name)
            raw = await asyncio.to_thread(provider.fetch_daily_bars, symbol, start, end)
            validated = validate_bars(symbol, raw)
            written += await repo.upsert_bars(benchmark_id, validated.valid, source=provider.name)
        ctx.records_processed = written
        ctx.meta = {"benchmarks": [s for s, _ in DEFAULT_BENCHMARKS], "bars_written": written}
        return written
