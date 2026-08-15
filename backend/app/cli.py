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
from app.services.intraday_ingest import ingest_intraday
from app.services.macro_ingest import ingest_macro
from app.services.providers import (
    get_broker,
    get_fundamentals_provider,
    get_intraday_provider,
    get_macro_provider,
    get_market_data_provider,
)
from app.services.scoring import score_universe_job
from app.services.signal_pipeline import run_signal_pipeline
from app.services.universe import seed_etfs, seed_universe

log = structlog.get_logger()


async def _seed() -> None:
    factory = get_session_factory()
    async with factory() as session:
        count = await seed_universe(session)
        etfs = await seed_etfs(session)
        bench = await seed_benchmarks(session)
        await session.commit()
    log.info("cli.seed.done", companies=count, etfs=etfs, benchmarks=bench)


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


async def _score() -> None:
    factory = get_session_factory()
    async with factory() as session:
        written = await score_universe_job(session)
    log.info("cli.score.done", rows=written)


async def _backfill_intraday(days: int, symbols: list[str] | None, interval: str) -> None:
    settings = get_settings()
    provider = get_intraday_provider(settings)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    factory = get_session_factory()
    async with factory() as session:
        report = await ingest_intraday(
            session, provider, start, end, interval=interval, symbols=symbols,
            job_name="backfill_intraday",
        )
    log.info(
        "cli.backfill_intraday.done",
        requested=report.requested,
        bars=report.bars_written,
        failed=len(report.failed),
        interval=interval,
    )


async def _signals() -> None:
    factory = get_session_factory()
    async with factory() as session:
        report = await run_signal_pipeline(session)
    log.info(
        "cli.signals.done",
        ts=report.ts.isoformat(),
        regime=report.regime,
        scored=report.scored,
        breadth=round(report.breadth, 3),
    )


async def _cycle() -> None:
    """Run one autonomous decision cycle now — the same code path the scheduler fires."""
    from app.services.decision_engine import run_decision_cycle

    settings = get_settings()
    broker = get_broker(settings)
    factory = get_session_factory()
    async with factory() as session:
        report = await run_decision_cycle(session, broker)
        await session.commit()
    log.info(
        "cli.cycle.done",
        cycle_id=str(report.cycle_id),
        regime=report.regime,
        scored=report.n_scored,
        buys=report.buys,
        sells=report.sells,
        holds=report.holds,
        skips=report.skips,
        halted=report.halted,
        halt_reason=report.halt_reason,
    )


async def _refresh() -> None:
    """Run the twice-daily price refresh now (trailing window ingest + rescore)."""
    from app.jobs.eod_ingest import run_eod_ingest

    await run_eod_ingest(job_name="manual_refresh")


async def _reconcile() -> None:
    """Re-sync the local position mirror from broker truth (fills land asynchronously)."""
    from app.services.reconciliation import reconcile_positions

    settings = get_settings()
    broker = get_broker(settings)
    factory = get_session_factory()
    async with factory() as session:
        report = await reconcile_positions(session, broker)
        await session.commit()
    log.info("cli.reconcile.done", report=report)


async def _sync_orders() -> None:
    """Advance open orders from broker truth and record any fills that landed late."""
    from app.services.order_sync import sync_open_orders

    settings = get_settings()
    broker = get_broker(settings)
    factory = get_session_factory()
    async with factory() as session:
        report = await sync_open_orders(session, broker)
        await session.commit()
    log.info(
        "cli.sync_orders.done",
        checked=report.checked,
        advanced=report.advanced,
        filled=report.filled,
        missing=report.missing,
    )


async def _backfill_equity(period: str, timeframe: str) -> None:
    """Seed the equity curve from the broker's own account history.

    For stretches where nothing of ours was running (worker down, cycle rejected mid-run),
    the broker still recorded what the account was worth. Gap-fill only: a timestamp that
    already has a live snapshot keeps it.
    """
    from app.services.snapshots import backfill_equity

    settings = get_settings()
    broker = get_broker(settings)
    factory = get_session_factory()
    async with factory() as session:
        inserted = await backfill_equity(session, broker, period, timeframe)
        await session.commit()
    log.info("cli.backfill_equity.done", inserted=inserted)


async def _backtest(start: str, end: str, cash: float) -> None:
    from datetime import date

    from app.backtest.runner import run_and_persist

    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    factory = get_session_factory()
    async with factory() as session:
        run_id, metrics = await run_and_persist(session, s, e, cash)
    spy = next((b for b in metrics.benchmarks if b.name == "SPY"), None)
    log.info(
        "cli.backtest.done",
        run_id=str(run_id),
        days=metrics.trading_days,
        total_return=round(metrics.total_return or 0.0, 4),
        cagr=round(metrics.cagr or 0.0, 4),
        sharpe=round(metrics.sharpe or 0.0, 3),
        max_drawdown=round(metrics.max_drawdown or 0.0, 4),
        trades=metrics.trades,
        win_rate=round(metrics.win_rate or 0.0, 3),
        cost_drag=metrics.cost_drag,
        vs_spy_excess=round(spy.excess_return or 0.0, 4) if spy else None,
        regime_days=metrics.regime_days,
    )


async def _rank_ic(start: str, end: str, horizon: int, step: int) -> None:
    from datetime import date

    from app.backtest.loader import load_backtest_data
    from app.backtest.rank_ic import evaluate_ranking

    factory = get_session_factory()
    async with factory() as session:
        data = await load_backtest_data(session)
    report = evaluate_ranking(
        data, date.fromisoformat(start), date.fromisoformat(end), horizon=horizon, step=step
    )
    log.info("cli.rank_ic.done", **report.to_dict())


async def _macro(years: int) -> None:
    settings = get_settings()
    fred = get_macro_provider(settings)
    # VIX comes from yfinance (FRED's keyless feed doesn't carry ^VIX).
    from app.adapters.yfinance_data import YFinanceMarketData

    end = datetime.now(UTC).date()
    start = end - timedelta(days=round(years * 365.25))
    factory = get_session_factory()
    async with factory() as session:
        report = await ingest_macro(session, fred, YFinanceMarketData(), start, end)
    log.info(
        "cli.macro.done",
        points=report.total_points,
        series=report.series_written,
        failed=report.failed,
    )


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

    sub.add_parser("score", help="Compute research scores for the whole universe")

    bfi = sub.add_parser("backfill-intraday", help="Backfill intraday bars (SP500 + ETFs)")
    bfi.add_argument("--days", type=int, default=5)
    bfi.add_argument("--symbols", type=str, default=None, help="comma-separated; default all")
    bfi.add_argument("--interval", type=str, default="15Min", help="15Min|30Min|1Hour")

    mac = sub.add_parser("macro", help="Ingest FRED rate/curve/inflation series + VIX")
    mac.add_argument("--years", type=int, default=5)

    sub.add_parser("signals", help="Run the v2 signal pipeline (regime + fused scores)")

    sub.add_parser("cycle", help="Run one autonomous decision cycle now (places paper orders)")

    sub.add_parser("reconcile", help="Re-sync the local position mirror from the broker")

    sub.add_parser("sync-orders", help="Advance open orders and record late fills")

    sub.add_parser("refresh", help="Run the daily price refresh + rescore now")

    bfe = sub.add_parser("backfill-equity", help="Seed the equity curve from broker history")
    bfe.add_argument("--period", type=str, default="1M", help="1D|1W|1M|3M|1A")
    bfe.add_argument("--timeframe", type=str, default="1H", help="1Min|5Min|15Min|1H|1D")

    ric = sub.add_parser("rank-ic", help="Measure ranking quality: rank IC + decile spread")
    ric.add_argument("--start", type=str, required=True, help="YYYY-MM-DD")
    ric.add_argument("--end", type=str, required=True, help="YYYY-MM-DD")
    ric.add_argument("--horizon", type=int, default=21, help="forward return, sessions")
    ric.add_argument("--step", type=int, default=21, help="sessions between eval dates")

    bt = sub.add_parser("backtest", help="Run a daily backtest of the v2 strategy")
    bt.add_argument("--start", type=str, required=True, help="YYYY-MM-DD")
    bt.add_argument("--end", type=str, required=True, help="YYYY-MM-DD")
    bt.add_argument("--cash", type=float, default=100_000.0)

    args = parser.parse_args()
    if args.command == "seed":
        asyncio.run(_seed())
    elif args.command == "backfill":
        asyncio.run(_backfill(args.years, _parse_symbols(args.symbols), args.batch))
    elif args.command == "fundamentals":
        asyncio.run(_fundamentals(_parse_symbols(args.symbols)))
    elif args.command == "score":
        asyncio.run(_score())
    elif args.command == "backfill-intraday":
        asyncio.run(
            _backfill_intraday(args.days, _parse_symbols(args.symbols), args.interval)
        )
    elif args.command == "macro":
        asyncio.run(_macro(args.years))
    elif args.command == "signals":
        asyncio.run(_signals())
    elif args.command == "cycle":
        asyncio.run(_cycle())
    elif args.command == "reconcile":
        asyncio.run(_reconcile())
    elif args.command == "sync-orders":
        asyncio.run(_sync_orders())
    elif args.command == "refresh":
        asyncio.run(_refresh())
    elif args.command == "backfill-equity":
        asyncio.run(_backfill_equity(args.period, args.timeframe))
    elif args.command == "rank-ic":
        asyncio.run(_rank_ic(args.start, args.end, args.horizon, args.step))
    elif args.command == "backtest":
        asyncio.run(_backtest(args.start, args.end, args.cash))


if __name__ == "__main__":
    main()
