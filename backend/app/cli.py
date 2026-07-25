"""Operational CLI: seed the universe and backfill prices.

Usage:
    uv run python -m app.cli seed
    uv run python -m app.cli backfill --years 2 [--symbols AAPL,MSFT] [--batch 100]

Backfill is batched and idempotent — re-running never creates duplicates.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.repositories.companies import CompanyRepository
from app.db.session import get_session_factory
from app.services.benchmarks import ingest_benchmarks, seed_benchmarks
from app.services.fundamentals_ingest import ingest_fundamentals
from app.services.ingest import ingest_prices
from app.services.providers import get_fundamentals_provider, get_market_data_provider
from app.services.universe import seed_universe

log = structlog.get_logger()


async def _seed() -> None:
    factory = get_session_factory()
    async with factory() as session:
        count = await seed_universe(session)
        bench = await seed_benchmarks(session)
    log.info("cli.seed.done", companies=count, benchmarks=bench)


async def _backfill(years: int, symbols: list[str] | None, batch: int) -> None:
    settings = get_settings()
    provider = get_market_data_provider(settings)
    end = datetime.now(UTC).date()
    start = end - timedelta(days=round(years * 365.25))

    factory = get_session_factory()
    async with factory() as session:
        await ingest_benchmarks(session, provider, start, end)
        if symbols is None:
            targets = [sym for _, sym in await CompanyRepository(session).active_symbols()]
        else:
            targets = [s.upper() for s in symbols]

    total_batches = (len(targets) + batch - 1) // batch
    for i in range(0, len(targets), batch):
        chunk = targets[i : i + batch]
        async with factory() as session:
            report = await ingest_prices(
                session, provider, start, end, symbols=chunk, job_name="backfill_prices"
            )
        log.info(
            "cli.backfill.batch",
            batch=i // batch + 1,
            of=total_batches,
            symbols=len(chunk),
            bars=report.bars_written,
            failed=len(report.failed),
        )
    log.info("cli.backfill.done", symbols=len(targets), start=str(start), end=str(end))


async def _fundamentals(symbols: list[str] | None) -> None:
    settings = get_settings()
    provider = get_fundamentals_provider(settings)
    factory = get_session_factory()
    async with factory() as session:
        report = await ingest_fundamentals(session, provider, symbols=symbols)
    log.info(
        "cli.fundamentals.done",
        requested=report.requested,
        records=report.records_written,
        failed=len(report.failed),
    )


def _parse_symbols(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [s.strip() for s in value.split(",") if s.strip()]


def main() -> None:
    configure_logging(get_settings().environment)
    parser = argparse.ArgumentParser(prog="blackoak")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="Seed S&P 500 universe and benchmarks")

    bf = sub.add_parser("backfill", help="Backfill daily prices")
    bf.add_argument("--years", type=int, default=2)
    bf.add_argument("--symbols", type=str, default=None, help="comma-separated; default all")
    bf.add_argument("--batch", type=int, default=100)

    fund = sub.add_parser("fundamentals", help="Ingest annual fundamentals")
    fund.add_argument("--symbols", type=str, default=None, help="comma-separated; default all")

    args = parser.parse_args()
    if args.command == "seed":
        asyncio.run(_seed())
    elif args.command == "backfill":
        asyncio.run(_backfill(args.years, _parse_symbols(args.symbols), args.batch))
    elif args.command == "fundamentals":
        asyncio.run(_fundamentals(_parse_symbols(args.symbols)))


if __name__ == "__main__":
    main()
