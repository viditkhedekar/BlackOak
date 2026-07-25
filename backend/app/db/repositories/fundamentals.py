from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Fundamental
from app.domain.fundamentals import AMOUNT_FIELDS, FundamentalRecord


class FundamentalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_records(
        self, company_id: uuid.UUID, records: list[FundamentalRecord], source: str
    ) -> int:
        """Idempotent write keyed by (company_id, period, fiscal_date)."""
        if not records:
            return 0
        rows = [
            {
                "company_id": company_id,
                "period": r.period,
                "fiscal_date": r.fiscal_date,
                "source": source,
                **{f: getattr(r, f) for f in AMOUNT_FIELDS},
            }
            for r in records
        ]
        stmt = pg_insert(Fundamental).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Fundamental.company_id, Fundamental.period, Fundamental.fiscal_date],
            set_={f: getattr(stmt.excluded, f) for f in (*AMOUNT_FIELDS, "source")},
        )
        await self._session.execute(stmt)
        return len(rows)

    async def get_annual(self, company_id: uuid.UUID) -> list[Fundamental]:
        result = await self._session.execute(
            select(Fundamental)
            .where(Fundamental.company_id == company_id, Fundamental.period == "FY")
            .order_by(Fundamental.fiscal_date)
        )
        return list(result.scalars().all())
