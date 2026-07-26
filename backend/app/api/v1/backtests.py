from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.backtests import BacktestRepository
from app.db.session import get_db_session
from app.schemas.dashboard import (
    BacktestDetail,
    BacktestEquityPoint,
    BacktestSummary,
    BacktestTradeRow,
)

router = APIRouter(prefix="/backtests", tags=["backtests"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _summary(run: object) -> BacktestSummary:
    return BacktestSummary(
        id=str(run.id),  # type: ignore[attr-defined]
        start_date=run.start_date,  # type: ignore[attr-defined]
        end_date=run.end_date,  # type: ignore[attr-defined]
        config_version=run.config_version,  # type: ignore[attr-defined]
        universe_size=run.universe_size,  # type: ignore[attr-defined]
        metrics=run.metrics,  # type: ignore[attr-defined]
        created_at=run.created_at,  # type: ignore[attr-defined]
    )


@router.get("", response_model=list[BacktestSummary])
async def list_backtests(session: SessionDep) -> list[BacktestSummary]:
    runs = await BacktestRepository(session).list_runs()
    return [_summary(r) for r in runs]


@router.get("/{run_id}", response_model=BacktestDetail)
async def backtest_detail(run_id: str, session: SessionDep) -> BacktestDetail:
    repo = BacktestRepository(session)
    try:
        rid = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(422, "invalid run id") from exc
    run = await repo.get_run(rid)
    if run is None:
        raise HTTPException(404, "backtest run not found")
    equity = await repo.equity_curve(rid)
    trades = await repo.trades(rid)
    return BacktestDetail(
        summary=_summary(run),
        equity_curve=[
            BacktestEquityPoint(day=e.day, equity=float(e.equity), regime=e.regime)
            for e in equity
        ],
        trades=[
            BacktestTradeRow(
                symbol=t.symbol, side=t.side, trade_date=t.trade_date,
                shares=float(t.shares), price=float(t.price), reason=t.reason,
                realized_pnl=float(t.realized_pnl),
            )
            for t in trades
        ],
    )
