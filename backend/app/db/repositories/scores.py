from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Row, and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, ResearchScore

# Category columns that can be sorted on in the screener.
SORTABLE = (
    "composite", "financial_health", "growth", "value", "quality",
    "profitability", "momentum", "volatility", "risk",
)
_UPSERT_COLS = (*SORTABLE, "data_completeness", "engine_version", "inputs")


class ScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_scores(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        stmt = pg_insert(ResearchScore).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                ResearchScore.company_id,
                ResearchScore.as_of_date,
                ResearchScore.profile,
            ],
            set_={col: getattr(stmt.excluded, col) for col in _UPSERT_COLS},
        )
        await self._session.execute(stmt)
        return len(rows)

    async def latest_as_of(self) -> date | None:
        result = await self._session.execute(select(func.max(ResearchScore.as_of_date)))
        return result.scalar_one_or_none()

    async def get_for_company(
        self, company_id: uuid.UUID, profile: str, as_of: date
    ) -> ResearchScore | None:
        result = await self._session.execute(
            select(ResearchScore).where(
                ResearchScore.company_id == company_id,
                ResearchScore.profile == profile,
                ResearchScore.as_of_date == as_of,
            )
        )
        return result.scalar_one_or_none()

    async def screener(
        self,
        *,
        profile: str,
        as_of: date,
        min_score: float | None,
        sector: str | None,
        sort_by: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Row[Any]], int]:
        sort_col = getattr(ResearchScore, sort_by if sort_by in SORTABLE else "composite")
        conditions = [
            ResearchScore.profile == profile,
            ResearchScore.as_of_date == as_of,
        ]
        if min_score is not None:
            conditions.append(ResearchScore.composite >= min_score)
        if sector is not None:
            conditions.append(Company.sector == sector)

        where = and_(*conditions)
        base = select(Company, ResearchScore).join(
            ResearchScore, ResearchScore.company_id == Company.id
        ).where(where)

        total_stmt = (
            select(func.count())
            .select_from(Company)
            .join(ResearchScore, ResearchScore.company_id == Company.id)
            .where(where)
        )
        total = int((await self._session.execute(total_stmt)).scalar_one())

        order = sort_col.desc() if descending else sort_col.asc()
        # NULLS LAST regardless of direction so unscored names never top the list.
        rows = await self._session.execute(
            base.order_by(order.nulls_last()).limit(limit).offset(offset)
        )
        return list(rows.all()), total
