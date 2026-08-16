from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


_BARE_POSTGRES_DRIVERS = {"postgresql", "postgres"}


def engine_args(database_url: str) -> tuple[str, dict[str, object]]:
    """Turn a hosted-Postgres connection string (Neon, Supabase, Render, ...) into
    something asyncpg will actually accept. Shared by the running app (``get_engine``
    below) and Alembic (``alembic/env.py``) so a migration run can't take a different,
    unfixed path than the app itself.

    Two problems, both from the same source: those dashboards copy out a plain libpq URL,
    not one written for asyncpg.

    1. A bare ``postgresql://`` (no ``+asyncpg``) resolves to SQLAlchemy's default driver
       for that dialect, which is the sync ``psycopg2`` — a package this project never
       installs, since everything here is async. The engine construction then dies trying
       to import a driver that was never a dependency, not with a helpful "wrong URL"
       error. Force the ``+asyncpg`` driver explicitly rather than trust the input.
    2. ``?sslmode=require`` (and Neon's ``&channel_binding=require``) are libpq-only query
       params; asyncpg's connector rejects unrecognized ones outright instead of ignoring
       them. Strip them and translate ``sslmode`` to asyncpg's own ``ssl`` connect arg.
    """
    url = make_url(database_url)
    if url.drivername in _BARE_POSTGRES_DRIVERS:
        url = url.set(drivername="postgresql+asyncpg")
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)  # libpq-only; asyncpg has no equivalent kwarg
    connect_args: dict[str, object] = {}
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = "require" if sslmode == "require" else True
    return url.set(query=query).render_as_string(hide_password=False), connect_args


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url, connect_args = engine_args(get_settings().database_url)
        _engine = create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
