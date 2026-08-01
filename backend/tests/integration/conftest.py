"""Integration fixtures: a real Postgres session.

Self-provisions any missing tables via metadata.create_all (so a developer who has only
run `docker compose up` still gets a usable schema), and skips the whole module if no
database is reachable (so a laptop without Postgres still gets a green unit-test run).

create_all is checkfirst, so it is a no-op against an already-migrated database — but it
never stamps alembic_version. Anything that runs `alembic upgrade head` on the same
database must therefore migrate BEFORE these tests touch it, or Alembic starts from base
against a fully-populated schema and fails on 0001 with `relation "users" already
exists`. That is why .github/workflows/ci.yml runs the migration steps ahead of pytest.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db import models  # noqa: F401  (register tables on Base.metadata)
from app.db.base import Base


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[object]:
    eng = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await eng.dispose()
        pytest.skip(f"No database reachable for integration tests: {exc}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine: object) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)  # type: ignore[arg-type]
    async with factory() as session:
        yield session
