"""Backtest runner: load snapshot → run engine → build metrics → persist.

The persistence boundary for the pure engine. Aligns SPY/RSP benchmark closes to the
equity-curve dates before computing benchmark-relative metrics.
"""

from __future__ import annotations

import uuid
from bisect import bisect_right
from datetime import date

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.engine import BacktestConfig, run_backtest
from app.backtest.loader import load_backtest_data
from app.backtest.report import BacktestMetrics, build_metrics
from app.db.models import BacktestEquity, BacktestRun, BacktestTrade
from app.db.repositories.companies import CompanyRepository
from app.db.repositories.prices import PriceRepository
from app.services.job_tracking import track_job

log = structlog.get_logger()


def _aligned_closes(
    curve_days: list[date], bench_dates: list[date], bench_closes: list[float]
) -> list[float]:
    """Benchmark close as-of each equity-curve day (last close <= day)."""
    out: list[float] = []
    for d in curve_days:
        i = bisect_right(bench_dates, d) - 1
        if i >= 0:
            out.append(bench_closes[i])
    return out


async def run_and_persist(
    session: AsyncSession, start: date, end: date, initial_cash: float = 100_000.0
) -> tuple[uuid.UUID, BacktestMetrics]:
    async with track_job(session, "backtest") as ctx:
        data = await load_backtest_data(session)
        config = BacktestConfig(start=start, end=end, initial_cash=initial_cash)
        result = run_backtest(data, config)

        curve_days = [p.day for p in result.equity_curve]
        companies = CompanyRepository(session)
        prices = PriceRepository(session)

        async def bench(symbol: str) -> list[float]:
            cid = await companies.get_id_by_symbol(symbol)
            if cid is None:
                return []
            rows = await prices.get_series(cid, None, None)
            return _aligned_closes(
                curve_days, [r.date for r in rows], [float(r.adj_close) for r in rows]
            )

        metrics = build_metrics(result, await bench("SPY"), await bench("RSP"))

        run = BacktestRun(
            start_date=start,
            end_date=end,
            config_version=config.config_version,
            initial_cash=initial_cash,
            universe_size=len(data.series),
            metrics=metrics.to_dict(),
        )
        session.add(run)
        await session.flush()  # populate run.id

        if result.trades:
            await session.execute(
                pg_insert(BacktestTrade),
                [
                    {
                        "run_id": run.id, "symbol": t.symbol, "side": t.side,
                        "trade_date": t.trade_date, "shares": t.shares, "price": t.price,
                        "reason": t.reason, "realized_pnl": t.realized_pnl,
                    }
                    for t in result.trades
                ],
            )
        if result.equity_curve:
            await session.execute(
                pg_insert(BacktestEquity),
                [
                    {
                        "run_id": run.id, "day": p.day, "equity": p.equity,
                        "cash": p.cash, "regime": p.regime, "positions": p.positions,
                    }
                    for p in result.equity_curve
                ],
            )

        ctx.records_processed = len(result.trades)
        ctx.meta = {
            "run_id": str(run.id),
            "trading_days": metrics.trading_days,
            "total_return": metrics.total_return,
            "trades": metrics.trades,
        }
        return run.id, metrics
