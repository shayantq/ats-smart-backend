import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.routers import health as health_router


@pytest.mark.asyncio
async def test_health_check_returns_200():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == settings.APP_VERSION


class _FakeRedis:
    def __init__(self, healthy: bool):
        self._healthy = healthy

    async def ping(self):
        if not self._healthy:
            raise ConnectionError("redis down")
        return True


@pytest.mark.asyncio
async def test_readiness_ok_when_database_and_redis_are_reachable(client, monkeypatch):
    monkeypatch.setattr(health_router, "get_redis_client", lambda: _FakeRedis(healthy=True))

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}


@pytest.mark.asyncio
async def test_readiness_returns_503_when_redis_is_down(client, monkeypatch):
    monkeypatch.setattr(health_router, "get_redis_client", lambda: _FakeRedis(healthy=False))

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {"database": "ok", "redis": "unavailable"}
