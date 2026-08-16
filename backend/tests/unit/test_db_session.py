"""Hosted-Postgres URL translation for the asyncpg driver.

Neon/Supabase/Render dashboards hand out plain libpq URLs — bare ``postgresql://`` (no
driver suffix), sometimes ``?sslmode=require`` and ``&channel_binding=require``. Two
distinct failure modes without this translation:

1. A bare ``postgresql://`` resolves to SQLAlchemy's default sync driver, psycopg2 — never
   installed here, since the whole app is async. This is exactly what broke the first
   Render deploy: ``ModuleNotFoundError: No module named 'psycopg2'``, from pasting Neon's
   connection string straight into the DATABASE_URL secret.
2. asyncpg's connector treats unknown query params as connect() kwargs and errors on ones
   it doesn't recognize (``sslmode``, ``channel_binding``), so even a correctly-scoped
   asyncpg URL copied verbatim from those dashboards fails to connect.
"""

from __future__ import annotations

from app.db.session import engine_args


def test_bare_postgresql_scheme_gets_the_asyncpg_driver() -> None:
    """The exact shape of the bug that broke the Render deploy."""
    url, _ = engine_args("postgresql://u:p@ep-foo.neon.tech/db")
    assert url.startswith("postgresql+asyncpg://")


def test_heroku_style_postgres_scheme_gets_the_asyncpg_driver() -> None:
    url, _ = engine_args("postgres://u:p@ep-foo.neon.tech/db")
    assert url.startswith("postgresql+asyncpg://")


def test_explicit_asyncpg_scheme_is_left_alone() -> None:
    url, _ = engine_args("postgresql+asyncpg://u:p@ep-foo.neon.tech/db")
    assert url.startswith("postgresql+asyncpg://")


def test_sslmode_require_becomes_asyncpg_ssl_arg() -> None:
    url, connect_args = engine_args(
        "postgresql+asyncpg://u:p@ep-foo.neon.tech/db?sslmode=require"
    )
    assert "sslmode" not in url
    assert connect_args == {"ssl": "require"}


def test_channel_binding_is_dropped_not_forwarded() -> None:
    url, connect_args = engine_args(
        "postgresql+asyncpg://u:p@ep-foo.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert "channel_binding" not in url
    assert connect_args == {"ssl": "require"}


def test_sslmode_disable_adds_no_connect_arg() -> None:
    url, connect_args = engine_args(
        "postgresql+asyncpg://u:p@localhost/db?sslmode=disable"
    )
    assert "sslmode" not in url
    assert connect_args == {}


def test_plain_local_url_is_untouched() -> None:
    original = "postgresql+asyncpg://blackoak:blackoak@localhost:5434/blackoak"
    url, connect_args = engine_args(original)
    assert url == original
    assert connect_args == {}


def test_credentials_and_other_params_survive() -> None:
    url, _ = engine_args(
        "postgresql+asyncpg://u:p@ep-foo.neon.tech/db?sslmode=require&application_name=blackoak"
    )
    assert "u:p@ep-foo.neon.tech/db" in url
    assert "application_name=blackoak" in url


def test_bare_scheme_and_sslmode_fix_together() -> None:
    """The real-world Neon connection string, unmodified, end to end."""
    url, connect_args = engine_args(
        "postgresql://u:p@ep-foo.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert url.startswith("postgresql+asyncpg://")
    assert "sslmode" not in url
    assert "channel_binding" not in url
    assert connect_args == {"ssl": "require"}
