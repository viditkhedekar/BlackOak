from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRun, PriceDaily
from app.db.repositories.macro import MacroRepository
from app.db.repositories.strategy import StrategyScoreRepository
from app.db.session import get_db_session
from app.schemas.dashboard import (
    FeedFreshness,
    JobRunRow,
    SystemHealthResponse,
)

router = APIRouter(prefix="/system", tags=["system"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/health", response_model=SystemHealthResponse)
async def system_health(session: SessionDep) -> SystemHealthResponse:
    job_rows = await session.execute(
        select(JobRun).order_by(JobRun.started_at.desc()).limit(20)
    )
    jobs = [
        JobRunRow(
            job_name=j.job_name, started_at=j.started_at, finished_at=j.finished_at,
            status=j.status, records_processed=j.records_processed, error=j.error,
        )
        for j in job_rows.scalars().all()
    ]

    feeds: list[FeedFreshness] = []
    for series_id, day in (await MacroRepository(session).latest_dates()).items():
        feeds.append(FeedFreshness(feed=f"macro:{series_id}", as_of=day.isoformat()))

    max_price = await session.execute(select(func.max(PriceDaily.date)))
    d = max_price.scalar_one_or_none()
    feeds.append(FeedFreshness(feed="prices_daily", as_of=d.isoformat() if d else None))

    ts = await StrategyScoreRepository(session).latest_ts()
    feeds.append(FeedFreshness(feed="strategy_scores", as_of=ts.isoformat() if ts else None))

    return SystemHealthResponse(jobs=jobs, feeds=feeds)
