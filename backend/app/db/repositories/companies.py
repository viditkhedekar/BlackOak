from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company


class CompanyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Insert or update companies keyed by symbol. Returns row count touched."""
        if not rows:
            return 0
        stmt = pg_insert(Company).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Company.symbol],
            set_={
                "name": stmt.excluded.name,
                "sector": stmt.excluded.sector,
                "industry": stmt.excluded.industry,
                "universe": stmt.excluded.universe,
                "is_active": stmt.excluded.is_active,
            },
        )
        await self._session.execute(stmt)
        return len(rows)

    async def get_by_symbol(self, symbol: str) -> Company | None:
        result = await self._session.execute(
            select(Company).where(Company.symbol == symbol.upper())
        )
        return result.scalar_one_or_none()

    async def get_id_by_symbol(self, symbol: str) -> uuid.UUID | None:
        result = await self._session.execute(
            select(Company.id).where(Company.symbol == symbol.upper())
        )
        return result.scalar_one_or_none()

    async def search(
        self, query: str | None, sector: str | None, limit: int, offset: int
    ) -> list[Company]:
        stmt = select(Company).where(Company.is_active.is_(True))
        if query:
            like = f"%{query.upper()}%"
            stmt = stmt.where(
                func.upper(Company.symbol).like(like) | func.upper(Company.name).like(like)
            )
        if sector:
            stmt = stmt.where(Company.sector == sector)
        stmt = stmt.order_by(Company.symbol).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, query: str | None, sector: str | None) -> int:
        stmt = select(func.count()).select_from(Company).where(Company.is_active.is_(True))
        if query:
            like = f"%{query.upper()}%"
            stmt = stmt.where(
                func.upper(Company.symbol).like(like) | func.upper(Company.name).like(like)
            )
        if sector:
            stmt = stmt.where(Company.sector == sector)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def active_symbols(self, universe: str = "SP500") -> list[tuple[uuid.UUID, str]]:
        return await self.active_symbols_in([universe])

    async def active_symbols_in(
        self, universes: list[str]
    ) -> list[tuple[uuid.UUID, str]]:
        """Active symbols across several universes (e.g. SP500 + ETF for intraday)."""
        result = await self._session.execute(
            select(Company.id, Company.symbol)
            .where(Company.is_active.is_(True), Company.universe.in_(universes))
            .order_by(Company.symbol)
        )
        return [(row[0], row[1]) for row in result.all()]
