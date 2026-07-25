from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def fake_db_ok() -> AsyncMock:
    """Session stub whose execute() succeeds — health should report db ok."""
    return AsyncMock()


@pytest.fixture
def fake_db_down() -> AsyncMock:
    session = AsyncMock()
    session.execute.side_effect = ConnectionError("db unreachable")
    return session


@pytest.fixture
async def client(request: pytest.FixtureRequest) -> AsyncIterator[AsyncClient]:
    """App client with the DB dependency overridden by the marked fixture."""
    marker = request.node.get_closest_marker("db_fixture")
    fixture_name = marker.args[0] if marker else "fake_db_ok"
    session: Any = request.getfixturevalue(fixture_name)

    async def override() -> AsyncIterator[Any]:
        yield session

    app.dependency_overrides[get_db_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "db_fixture(name): which fake DB session fixture to use")
