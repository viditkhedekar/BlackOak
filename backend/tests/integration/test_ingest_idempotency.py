"""The core pipeline invariant: re-running ingest never creates duplicate rows."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, JobRun, PriceDaily
from app.db.repositories.companies import CompanyRepository
from app.domain.market_data import Bar
from app.services.ingest import ingest_prices

_TEST_SYMBOL = "ZZTEST"


class _FakeProvider:
    """Deterministic MarketDataProvider — no network, fixed bars."""

    name = "fake"

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        return [
            Bar(symbol, date(2026, 1, 2), Decimal("10"), Decimal("11"),
                Decimal("9"), Decimal("10.5"), Decimal("10.5"), 1000),
            Bar(symbol, date(2026, 1, 5), Decimal("10.5"), Decimal("12"),
                Decimal("10"), Decimal("11"), Decimal("11"), 1200),
        ]


@pytest.fixture
async def seeded_company(db_session: AsyncSession):
    await CompanyRepository(db_session).upsert_many(
        [{"symbol": _TEST_SYMBOL, "name": "Test Co", "sector": "Testing",
          "industry": "Testing", "universe": "TEST", "is_active": True}]
    )
    await db_session.commit()
    yield
    await db_session.execute(delete(Company).where(Company.symbol == _TEST_SYMBOL))
    await db_session.execute(delete(JobRun).where(JobRun.job_name == "test_ingest"))
    await db_session.commit()


async def _price_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(PriceDaily)
        .join(Company, Company.id == PriceDaily.company_id)
        .where(Company.symbol == _TEST_SYMBOL)
    )
    return int(result.scalar_one())


async def test_reingest_produces_no_duplicates(
    db_session: AsyncSession, seeded_company: None
) -> None:
    provider = _FakeProvider()
    args = (db_session, provider, date(2026, 1, 1), date(2026, 1, 6))

    first = await ingest_prices(*args, symbols=[_TEST_SYMBOL], job_name="test_ingest")
    assert first.bars_written == 2
    assert await _price_count(db_session) == 2

    second = await ingest_prices(*args, symbols=[_TEST_SYMBOL], job_name="test_ingest")
    assert second.bars_written == 2  # wrote (upserted) again...
    assert await _price_count(db_session) == 2  # ...but row count is unchanged
