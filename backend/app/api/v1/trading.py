from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import JobRun
from app.db.repositories.benchmarks import BenchmarkRepository
from app.db.repositories.trading import (
    PortfolioSnapshotRepository,
    PositionRepository,
    ThesisRepository,
)
from app.db.session import get_db_session
from app.domain.calendar import is_trading_day
from app.schemas.dashboard import (
    EquityPoint,
    PerformanceResponse,
    PortfolioResponse,
    PositionRow,
    ScheduleResponse,
)
from app.services.schedule import CYCLE_HOURS, ET, next_cycle_at

router = APIRouter(tags=["trading"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

# Jobs only the worker runs — a recent row for any of them means a worker is alive. CLI
# jobs (backfill, manual scoring) are excluded so a hand-run command can't fake a heartbeat.
WORKER_JOBS = ("decision_cycle", "intraday_poll", "eod_ingest_preopen", "eod_ingest_postclose")
# The intraday poll fires every 15 min; one missed beat plus slack means the worker is gone.
HEARTBEAT_STALE_MINUTES = 20
POLL_START_HOUR = 9
POLL_END_HOUR = 16


def _num(v: object) -> float | None:
    return float(v) if v is not None else None  # type: ignore[arg-type]


@router.get("/portfolio", response_model=PortfolioResponse)
async def portfolio(session: SessionDep) -> PortfolioResponse:
    positions = await PositionRepository(session).all()
    theses = {t.symbol: t for t in await ThesisRepository(session).all()}
    snap = await PortfolioSnapshotRepository(session).latest()
    rows: list[PositionRow] = []
    for p in positions:
        t = theses.get(p.symbol)
        rows.append(
            PositionRow(
                symbol=p.symbol, shares=float(p.shares),
                avg_entry_price=float(p.avg_entry_price),
                stop_price=_num(t.stop_price) if t else None,
                target_price=_num(t.target_price) if t else None,
                entry_composite=_num(t.entry_composite) if t else None,
            )
        )
    return PortfolioResponse(
        ts=snap.ts if snap else None,
        equity=_num(snap.equity) if snap else None,
        cash=_num(snap.cash) if snap else None,
        regime=snap.regime if snap else None,
        positions=rows,
    )


@router.get("/schedule", response_model=ScheduleResponse)
async def schedule(session: SessionDep) -> ScheduleResponse:
    """When the next decision cycle runs, and whether a worker is alive to run it."""
    settings = get_settings()
    now = datetime.now(UTC)

    # The intraday poll is the worker's heartbeat: every 15 min through the session.
    last = await session.execute(
        select(func.max(JobRun.started_at)).where(JobRun.job_name.in_(WORKER_JOBS))
    )
    last_seen = last.scalar_one_or_none()

    et_now = now.astimezone(ET)
    in_session = (
        is_trading_day(et_now.date())
        and POLL_START_HOUR <= et_now.hour < POLL_END_HOUR
    )
    running = (
        last_seen is not None
        and (now - last_seen) <= timedelta(minutes=HEARTBEAT_STALE_MINUTES)
    )

    return ScheduleResponse(
        next_cycle_at=next_cycle_at(settings.cycle_interval_minutes, now),
        interval_minutes=settings.cycle_interval_minutes,
        cycle_window_et=f"{CYCLE_HOURS.split('-')[0]}:00-{CYCLE_HOURS.split('-')[1]}:00 ET",
        server_time=now,
        worker_last_seen=last_seen,
        worker_running=running,
        market_hours=in_session,
    )


@router.get("/performance", response_model=PerformanceResponse)
async def performance(session: SessionDep) -> PerformanceResponse:
    # Snapshots now land every 15 min during RTH (~26/day), so 500 was under three weeks
    # of curve. The limit takes the *newest* rows, which would also quietly re-base
    # total_return onto the window start rather than the true first point.
    snaps = await PortfolioSnapshotRepository(session).series(limit=5000)
    points = [
        EquityPoint(
            ts=s.ts, equity=float(s.equity), cash=_num(s.cash),
            regime=s.regime, positions=s.positions, source=s.source,
        )
        for s in snaps
    ]
    # Align SPY closes to the snapshot days for a benchmark overlay. SPY is a benchmark,
    # not a universe member — the ingest writes its bars to benchmark_prices, and it has
    # no rows in prices_daily, so reading it as a company yields an all-zero overlay.
    spy_id = await BenchmarkRepository(session).get_id_by_symbol("SPY")
    spy_aligned: list[float] = []
    spy_return: float | None = None
    if spy_id and points:
        spy_rows = await BenchmarkRepository(session).get_series(spy_id, None, None)
        dates = [r.date for r in spy_rows]
        closes = [float(r.adj_close) for r in spy_rows]
        if closes:
            for pt in points:
                i = bisect_right(dates, pt.ts.date()) - 1
                spy_aligned.append(closes[i] if i >= 0 else closes[0])
            if spy_aligned[0] > 0:
                spy_return = spy_aligned[-1] / spy_aligned[0] - 1.0

    start_equity = points[0].equity if points else None
    total_return = (
        points[-1].equity / start_equity - 1.0
        if start_equity and start_equity > 0 else None
    )
    return PerformanceResponse(
        points=points, spy=spy_aligned, start_equity=start_equity,
        total_return=total_return, spy_return=spy_return,
    )
