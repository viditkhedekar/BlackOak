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


def _engine_args(database_url: str) -> tuple[str, dict[str, object]]:
    """Strip libpq-only query params and translate ``sslmode`` to asyncpg's own ``ssl``
    connect arg. Hosted Postgres (Neon, Supabase, Render) hands out URLs with
    ``?sslmode=require`` (and Neon often adds ``channel_binding=require``), but asyncpg's
    connector rejects unrecognized query params outright rather than ignoring them, so a
    URL copied verbatim from those dashboards fails to connect at all."""
    url = make_url(database_url)
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
        url, connect_args = _engine_args(get_settings().database_url)
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
