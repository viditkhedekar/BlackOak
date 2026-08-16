import asyncio
from logging.config import fileConfig

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import get_settings
from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.db.session import engine_args

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Goes through the same URL prep as the running app (app/db/session.py): forces the
# asyncpg driver on a bare hosted-Postgres URL and strips libpq-only query params asyncpg
# rejects. Without this, a migration run against Neon/Supabase/Render takes a different,
# unfixed path than the app itself and fails on a URL the app connects to just fine.
_URL, _CONNECT_ARGS = engine_args(get_settings().database_url)
config.set_main_option("sqlalchemy.url", _URL)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # Built directly (not async_engine_from_config) because that helper reads engine
    # kwargs from the ini section's string values and has no way to carry the ssl
    # connect_args engine_args() computed above.
    connectable = create_async_engine(_URL, poolclass=pool.NullPool, connect_args=_CONNECT_ARGS)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
