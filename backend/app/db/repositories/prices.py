from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PriceDaily
from app.domain.market_data import Bar

_UPSERT_COLUMNS = ("open", "high", "low", "close", "adj_close", "volume", "source")


class PriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_bars(self, company_id: uuid.UUID, bars: list[Bar], source: str) -> int:
        """Idempotent write of a symbol's bars. Re-running yields zero duplicates
        because the composite PK (company_id, date) drives ON CONFLICT DO UPDATE."""
        if not bars:
            return 0
        rows = [
            {
                "company_id": company_id,
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adj_close": bar.adj_close,
                "volume": bar.volume,
                "source": source,
            }
            for bar in bars
        ]
        stmt = pg_insert(PriceDaily).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PriceDaily.company_id, PriceDaily.date],
            set_={col: getattr(stmt.excluded, col) for col in _UPSERT_COLUMNS},
        )
        await self._session.execute(stmt)
        return len(rows)

    async def get_series(
        self, company_id: uuid.UUID, start: date | None, end: date | None
    ) -> list[PriceDaily]:
        stmt = select(PriceDaily).where(PriceDaily.company_id == company_id)
        if start is not None:
            stmt = stmt.where(PriceDaily.date >= start)
        if end is not None:
            stmt = stmt.where(PriceDaily.date <= end)
        stmt = stmt.order_by(PriceDaily.date)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest_date(self, company_id: uuid.UUID) -> date | None:
        result = await self._session.execute(
            select(PriceDaily.date)
            .where(PriceDaily.company_id == company_id)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
