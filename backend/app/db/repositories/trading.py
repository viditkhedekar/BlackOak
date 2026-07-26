from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Execution,
    Order,
    PortfolioSnapshot,
    Position,
    PositionThesis,
    TradeDecision,
)


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, row: dict[str, object]) -> Order:
        order = Order(**row)
        self._session.add(order)
        await self._session.flush()
        return order

    async def by_client_id(self, client_order_id: uuid.UUID) -> Order | None:
        result = await self._session.execute(
            select(Order).where(Order.client_order_id == client_order_id)
        )
        return result.scalar_one_or_none()


class ExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, row: dict[str, object]) -> None:
        self._session.add(Execution(**row))


class PositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> list[Position]:
        result = await self._session.execute(select(Position))
        return list(result.scalars().all())

    async def upsert(self, row: dict[str, object]) -> None:
        stmt = pg_insert(Position).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Position.symbol],
            set_={
                "shares": stmt.excluded.shares,
                "avg_entry_price": stmt.excluded.avg_entry_price,
                "last_synced_at": stmt.excluded.last_synced_at,
            },
        )
        await self._session.execute(stmt)

    async def delete_symbol(self, symbol: str) -> None:
        await self._session.execute(delete(Position).where(Position.symbol == symbol))


class ThesisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> list[PositionThesis]:
        result = await self._session.execute(select(PositionThesis))
        return list(result.scalars().all())

    async def get(self, symbol: str) -> PositionThesis | None:
        result = await self._session.execute(
            select(PositionThesis).where(PositionThesis.symbol == symbol)
        )
        return result.scalar_one_or_none()

    async def upsert(self, row: dict[str, object]) -> None:
        stmt = pg_insert(PositionThesis).values([row])
        update_cols = {
            k: getattr(stmt.excluded, k)
            for k in row
            if k != "symbol"
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[PositionThesis.symbol], set_=update_cols
        )
        await self._session.execute(stmt)

    async def delete_symbol(self, symbol: str) -> None:
        await self._session.execute(
            delete(PositionThesis).where(PositionThesis.symbol == symbol)
        )


class TradeDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_many(self, rows: list[dict[str, object]]) -> int:
        if not rows:
            return 0
        await self._session.execute(pg_insert(TradeDecision), rows)
        return len(rows)

    async def for_cycle(self, cycle_id: uuid.UUID) -> list[TradeDecision]:
        result = await self._session.execute(
            select(TradeDecision).where(TradeDecision.cycle_id == cycle_id)
        )
        return list(result.scalars().all())

    async def recent(
        self, limit: int = 100, action: str | None = None, symbol: str | None = None
    ) -> list[TradeDecision]:
        stmt = select(TradeDecision)
        if action:
            stmt = stmt.where(TradeDecision.action == action)
        if symbol:
            stmt = stmt.where(TradeDecision.symbol == symbol.upper())
        stmt = stmt.order_by(TradeDecision.ts.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class PortfolioSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, row: dict[str, object]) -> None:
        stmt = pg_insert(PortfolioSnapshot).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=[PortfolioSnapshot.ts],
            set_={
                "equity": stmt.excluded.equity, "cash": stmt.excluded.cash,
                "positions": stmt.excluded.positions, "regime": stmt.excluded.regime,
                "holdings": stmt.excluded.holdings,
            },
        )
        await self._session.execute(stmt)

    async def latest_before(self, ts: datetime) -> PortfolioSnapshot | None:
        result = await self._session.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.ts < ts)
            .order_by(PortfolioSnapshot.ts.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def series(self, limit: int = 500) -> list[PortfolioSnapshot]:
        result = await self._session.execute(
            select(PortfolioSnapshot).order_by(PortfolioSnapshot.ts.desc()).limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def latest(self) -> PortfolioSnapshot | None:
        result = await self._session.execute(
            select(PortfolioSnapshot).order_by(PortfolioSnapshot.ts.desc()).limit(1)
        )
        return result.scalar_one_or_none()
