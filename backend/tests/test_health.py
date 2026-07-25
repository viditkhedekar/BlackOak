import pytest
from httpx import AsyncClient


async def test_health_ok_when_db_reachable(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


@pytest.mark.db_fixture("fake_db_down")
async def test_health_degraded_when_db_unreachable(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "unreachable"


async def test_unversioned_health_alias(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
