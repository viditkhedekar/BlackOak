from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Estimate
from app.domain.fundamentals import EstimateRecord

_UPSERT_COLUMNS = ("forward_eps", "forward_pe", "peg", "source")


class EstimatesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, company_id: uuid.UUID, record: EstimateRecord, source: str) -> int:
        """Idempotent write keyed by (company_id, as_of_date) — re-ingesting the same
        day overwrites rather than duplicating the rolling snapshot."""
        row = {
            "company_id": company_id,
            "as_of_date": record.as_of_date,
            "forward_eps": record.forward_eps,
            "forward_pe": record.forward_pe,
            "peg": record.peg,
            "source": source,
        }
        stmt = pg_insert(Estimate).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Estimate.company_id, Estimate.as_of_date],
            set_={col: getattr(stmt.excluded, col) for col in _UPSERT_COLUMNS},
        )
        await self._session.execute(stmt)
        return 1

    async def latest(self, company_id: uuid.UUID) -> Estimate | None:
        result = await self._session.execute(
            select(Estimate)
            .where(Estimate.company_id == company_id)
            .order_by(Estimate.as_of_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
