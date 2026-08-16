"""Hosted-Postgres URL translation for the asyncpg driver.

Neon/Supabase/Render hand out libpq-style URLs (``?sslmode=require``, sometimes
``&channel_binding=require``). asyncpg's connector treats unknown query params as
connect() kwargs and errors on ones it doesn't recognize, so a URL pasted straight from
those dashboards would fail to connect at all without this translation.
"""

from __future__ import annotations

from app.db.session import _engine_args


def test_sslmode_require_becomes_asyncpg_ssl_arg() -> None:
    url, connect_args = _engine_args(
        "postgresql+asyncpg://u:p@ep-foo.neon.tech/db?sslmode=require"
    )
    assert "sslmode" not in url
    assert connect_args == {"ssl": "require"}


def test_channel_binding_is_dropped_not_forwarded() -> None:
    url, connect_args = _engine_args(
        "postgresql+asyncpg://u:p@ep-foo.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert "channel_binding" not in url
    assert connect_args == {"ssl": "require"}


def test_sslmode_disable_adds_no_connect_arg() -> None:
    url, connect_args = _engine_args(
        "postgresql+asyncpg://u:p@localhost/db?sslmode=disable"
    )
    assert "sslmode" not in url
    assert connect_args == {}


def test_plain_local_url_is_untouched() -> None:
    original = "postgresql+asyncpg://blackoak:blackoak@localhost:5434/blackoak"
    url, connect_args = _engine_args(original)
    assert url == original
    assert connect_args == {}


def test_credentials_and_other_params_survive() -> None:
    url, _ = _engine_args(
        "postgresql+asyncpg://u:p@ep-foo.neon.tech/db?sslmode=require&application_name=blackoak"
    )
    assert "u:p@ep-foo.neon.tech/db" in url
    assert "application_name=blackoak" in url
