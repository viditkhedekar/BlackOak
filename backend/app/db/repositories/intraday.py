from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BarIntraday
from app.domain.market_data import IntradayBar

_UPSERT_COLUMNS = ("open", "high", "low", "close", "volume", "source")


class IntradayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_bars(
        self, company_id: uuid.UUID, bars: list[IntradayBar], source: str, interval: str = "15Min"
    ) -> int:
        """Idempotent write keyed on (company_id, ts, interval)."""
        if not bars:
            return 0
        rows = [
            {
                "company_id": company_id,
                "ts": bar.ts,
                "interval": interval,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": source,
            }
            for bar in bars
        ]
        stmt = pg_insert(BarIntraday).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[BarIntraday.company_id, BarIntraday.ts, BarIntraday.interval],
            set_={col: getattr(stmt.excluded, col) for col in _UPSERT_COLUMNS},
        )
        await self._session.execute(stmt)
        return len(rows)

    async def get_series(
        self,
        company_id: uuid.UUID,
        start: datetime | None,
        end: datetime | None,
        interval: str = "15Min",
    ) -> list[BarIntraday]:
        stmt = select(BarIntraday).where(
            BarIntraday.company_id == company_id, BarIntraday.interval == interval
        )
        if start is not None:
            stmt = stmt.where(BarIntraday.ts >= start)
        if end is not None:
            stmt = stmt.where(BarIntraday.ts <= end)
        stmt = stmt.order_by(BarIntraday.ts)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest_ts(self, company_id: uuid.UUID, interval: str = "15Min") -> datetime | None:
        result = await self._session.execute(
            select(func.max(BarIntraday.ts)).where(
                BarIntraday.company_id == company_id, BarIntraday.interval == interval
            )
        )
        return result.scalar_one_or_none()

    async def distinct_ts_count(self, since: datetime, interval: str = "15Min") -> int:
        """How many distinct interval timestamps exist since ``since`` — used by the
        data-freshness gate and the R0 zero-gaps verification."""
        result = await self._session.execute(
            select(func.count(func.distinct(BarIntraday.ts))).where(
                BarIntraday.ts >= since, BarIntraday.interval == interval
            )
        )
        return int(result.scalar_one())

    async def prune_before(self, cutoff: datetime) -> int:
        """Delete bars older than ``cutoff`` (nightly retention). Returns rows removed."""
        result = await self._session.execute(
            delete(BarIntraday).where(BarIntraday.ts < cutoff)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
