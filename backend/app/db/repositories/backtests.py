from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BacktestEquity, BacktestRun, BacktestTrade


class BacktestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_runs(self, limit: int = 25) -> list[BacktestRun]:
        result = await self._session.execute(
            select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get_run(self, run_id: uuid.UUID) -> BacktestRun | None:
        result = await self._session.execute(
            select(BacktestRun).where(BacktestRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def equity_curve(self, run_id: uuid.UUID) -> list[BacktestEquity]:
        result = await self._session.execute(
            select(BacktestEquity)
            .where(BacktestEquity.run_id == run_id)
            .order_by(BacktestEquity.day)
        )
        return list(result.scalars().all())

    async def trades(self, run_id: uuid.UUID) -> list[BacktestTrade]:
        result = await self._session.execute(
            select(BacktestTrade)
            .where(BacktestTrade.run_id == run_id)
            .order_by(BacktestTrade.trade_date)
        )
        return list(result.scalars().all())
