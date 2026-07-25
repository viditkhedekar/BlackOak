"""Company + price API routes against a real DB (routes → repositories → Postgres)."""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, PriceDaily
from app.db.repositories.companies import CompanyRepository
from app.db.repositories.prices import PriceRepository
from app.db.session import get_db_session
from app.domain.market_data import Bar
from app.main import app

_SYMBOL = "ZZAPI"


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[None]:
    repo = CompanyRepository(db_session)
    await repo.upsert_many(
        [{"symbol": _SYMBOL, "name": "Zeta API Corp", "sector": "Testing",
          "industry": "Testing", "universe": "TEST", "is_active": True}]
    )
    cid = await repo.get_id_by_symbol(_SYMBOL)
    assert cid is not None
    await PriceRepository(db_session).upsert_bars(
        cid,
        [Bar(_SYMBOL, date(2026, 1, 2), Decimal("10"), Decimal("11"),
             Decimal("9"), Decimal("10.5"), Decimal("10.5"), 1000)],
        source="test",
    )
    await db_session.commit()
    yield
    await db_session.execute(delete(PriceDaily).where(PriceDaily.company_id == cid))
    await db_session.execute(delete(Company).where(Company.symbol == _SYMBOL))
    await db_session.commit()


@pytest_asyncio.fixture
async def api(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_search_finds_seeded_company(api: AsyncClient, seeded: None) -> None:
    resp = await api.get("/api/v1/companies", params={"query": "zeta"})
    assert resp.status_code == 200
    symbols = [i["symbol"] for i in resp.json()["items"]]
    assert _SYMBOL in symbols


async def test_detail_and_prices(api: AsyncClient, seeded: None) -> None:
    detail = await api.get(f"/api/v1/companies/{_SYMBOL}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Zeta API Corp"

    prices = await api.get(f"/api/v1/companies/{_SYMBOL}/prices", params={"range": "1Y"})
    assert prices.status_code == 200
    assert len(prices.json()["points"]) == 1


async def test_unknown_symbol_404(api: AsyncClient) -> None:
    resp = await api.get("/api/v1/companies/NOPE404")
    assert resp.status_code == 404


async def test_invalid_range_422(api: AsyncClient, seeded: None) -> None:
    resp = await api.get(f"/api/v1/companies/{_SYMBOL}/prices", params={"range": "99Q"})
    assert resp.status_code == 422
