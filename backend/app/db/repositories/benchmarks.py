from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Benchmark, BenchmarkPrice
from app.domain.market_data import Bar

_UPSERT_COLUMNS = ("open", "high", "low", "close", "adj_close", "volume", "source")


class BenchmarkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, symbol: str, name: str) -> uuid.UUID:
        insert_stmt = pg_insert(Benchmark).values(symbol=symbol.upper(), name=name)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[Benchmark.symbol], set_={"name": insert_stmt.excluded.name}
        ).returning(Benchmark.id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_id_by_symbol(self, symbol: str) -> uuid.UUID | None:
        result = await self._session.execute(
            select(Benchmark.id).where(Benchmark.symbol == symbol.upper())
        )
        return result.scalar_one_or_none()

    async def upsert_bars(self, benchmark_id: uuid.UUID, bars: list[Bar], source: str) -> int:
        if not bars:
            return 0
        rows = [
            {
                "benchmark_id": benchmark_id,
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
        stmt = pg_insert(BenchmarkPrice).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[BenchmarkPrice.benchmark_id, BenchmarkPrice.date],
            set_={col: getattr(stmt.excluded, col) for col in _UPSERT_COLUMNS},
        )
        await self._session.execute(stmt)
        return len(rows)

    async def get_series(
        self, benchmark_id: uuid.UUID, start: date | None, end: date | None
    ) -> list[BenchmarkPrice]:
        stmt = select(BenchmarkPrice).where(BenchmarkPrice.benchmark_id == benchmark_id)
        if start is not None:
            stmt = stmt.where(BenchmarkPrice.date >= start)
        if end is not None:
            stmt = stmt.where(BenchmarkPrice.date <= end)
        result = await self._session.execute(stmt.order_by(BenchmarkPrice.date))
        return list(result.scalars().all())
