from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MacroSeries
from app.domain.macro import MacroPoint


class MacroRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_points(self, points: list[MacroPoint]) -> int:
        """Idempotent write keyed on (series_id, date)."""
        if not points:
            return 0
        rows = [
            {"series_id": p.series_id, "date": p.date, "value": p.value} for p in points
        ]
        stmt = pg_insert(MacroSeries).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MacroSeries.series_id, MacroSeries.date],
            set_={"value": stmt.excluded.value},
        )
        await self._session.execute(stmt)
        return len(rows)

    async def get_series(
        self, series_id: str, start: date | None = None, end: date | None = None
    ) -> list[MacroSeries]:
        stmt = select(MacroSeries).where(MacroSeries.series_id == series_id)
        if start is not None:
            stmt = stmt.where(MacroSeries.date >= start)
        if end is not None:
            stmt = stmt.where(MacroSeries.date <= end)
        stmt = stmt.order_by(MacroSeries.date)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest(self, series_id: str) -> MacroSeries | None:
        result = await self._session.execute(
            select(MacroSeries)
            .where(MacroSeries.series_id == series_id)
            .order_by(MacroSeries.date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_dates(self) -> dict[str, date]:
        """Most-recent observation date per series — feeds the System Health freshness view."""
        result = await self._session.execute(
            select(MacroSeries.series_id, func.max(MacroSeries.date)).group_by(
                MacroSeries.series_id
            )
        )
        return {row[0]: row[1] for row in result.all()}
