from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Row, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, RegimeSnapshot, StrategyScore

_FAMILY_COLUMNS = ("valuation", "fundamentals", "momentum", "technical", "risk")
_UPSERT_COLUMNS = (
    *_FAMILY_COLUMNS, "composite", "composite_percentile", "rank", "regime",
    "data_completeness", "engine_version", "weights_used", "inputs",
)


class StrategyScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_scores(self, rows: list[dict[str, object]]) -> int:
        """Idempotent write keyed on (company_id, ts)."""
        if not rows:
            return 0
        stmt = pg_insert(StrategyScore).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[StrategyScore.company_id, StrategyScore.ts],
            set_={c: getattr(stmt.excluded, c) for c in _UPSERT_COLUMNS},
        )
        await self._session.execute(stmt)
        return len(rows)

    async def latest_ts(self) -> datetime | None:
        result = await self._session.execute(select(func.max(StrategyScore.ts)))
        return result.scalar_one_or_none()

    async def top_ranked(
        self, ts: datetime, limit: int = 50, offset: int = 0
    ) -> list[Row[tuple[Company, StrategyScore]]]:
        stmt = (
            select(Company, StrategyScore)
            .join(Company, Company.id == StrategyScore.company_id)
            .where(StrategyScore.ts == ts)
            .order_by(StrategyScore.rank.asc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.all())

    async def get_for_company(
        self, company_id: uuid.UUID, ts: datetime
    ) -> StrategyScore | None:
        result = await self._session.execute(
            select(StrategyScore).where(
                StrategyScore.company_id == company_id, StrategyScore.ts == ts
            )
        )
        return result.scalar_one_or_none()


class RegimeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, row: dict[str, object]) -> None:
        await self._session.execute(pg_insert(RegimeSnapshot).values([row]))

    async def latest(self) -> RegimeSnapshot | None:
        result = await self._session.execute(
            select(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def recent_raw_labels(self, limit: int = 5) -> list[str]:
        """Recent raw labels, oldest-first, for the 2-day confirmation rule."""
        result = await self._session.execute(
            select(RegimeSnapshot.raw_label)
            .order_by(RegimeSnapshot.ts.desc())
            .limit(limit)
        )
        return [r[0] for r in reversed(result.all())]
