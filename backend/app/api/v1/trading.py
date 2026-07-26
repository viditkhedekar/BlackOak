from __future__ import annotations

from bisect import bisect_right
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.db.repositories.prices import PriceRepository
from app.db.repositories.trading import (
    PortfolioSnapshotRepository,
    PositionRepository,
    ThesisRepository,
)
from app.db.session import get_db_session
from app.schemas.dashboard import (
    EquityPoint,
    PerformanceResponse,
    PortfolioResponse,
    PositionRow,
)

router = APIRouter(tags=["trading"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


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


@router.get("/performance", response_model=PerformanceResponse)
async def performance(session: SessionDep) -> PerformanceResponse:
    snaps = await PortfolioSnapshotRepository(session).series(limit=500)
    points = [
        EquityPoint(
            ts=s.ts, equity=float(s.equity), cash=float(s.cash),
            regime=s.regime, positions=s.positions,
        )
        for s in snaps
    ]
    # Align SPY closes to the snapshot days for a benchmark overlay.
    companies = CompanyRepository(session)
    spy = await companies.get_by_symbol("SPY")
    spy_aligned: list[float] = []
    spy_return: float | None = None
    if spy and points:
        spy_rows = await PriceRepository(session).get_series(spy.id, None, None)
        dates = [r.date for r in spy_rows]
        closes = [float(r.adj_close) for r in spy_rows]
        for pt in points:
            i = bisect_right(dates, pt.ts.date()) - 1
            spy_aligned.append(closes[i] if i >= 0 else (closes[0] if closes else 0.0))
        if spy_aligned and spy_aligned[0] > 0:
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
