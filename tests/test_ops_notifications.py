"""
تست کانال پیام‌رسان داخل سایت تیم فنی:
- وب‌هوک Alertmanager و گزارش CI/CD (app/routers/ops.py) فقط با توکن عملیاتی معتبر
  پذیرفته می‌شوند و بدون تنظیم توکن، کاملاً غیرفعال‌اند (503).
- هر پیام برای همه‌ی اعضای فعال تیم فنی (نقش Admin) — و فقط آن‌ها — اعلان می‌سازد.
- صندوق اعلان‌ها (app/routers/notifications.py) فقط اعلان‌های خودِ کاربر را نشان می‌دهد.

مثل tests/test_pagination.py روی SQLite در حافظه اجرا می‌شود؛ فقط دو جدول users و
notifications ساخته می‌شوند (بقیه‌ی جدول‌ها نوع‌های مخصوص PostgreSQL مثل ARRAY/JSONB دارند).
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import deps
from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models import Base, Notification, User
from app.routers.ops import format_alert_message
from app.schemas.ops import AlertmanagerAlert

OPS_TOKEN = "test-ops-token"

ALERTMANAGER_PAYLOAD = {
    "version": "4",
    "status": "firing",
    "receiver": "ats-in-app",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HostHighMemoryUsage", "severity": "critical", "instance": "node_exporter:9100"},
            "annotations": {"summary": "مصرف RAM سرور از ۸۵٪ عبور کرد", "description": "مصرف فعلی حافظه: 91.2٪"},
            "startsAt": "2026-10-08T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
        }
    ],
}


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[User.__table__, Notification.__table__])

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        admin = User(email="admin@example.com", password_hash="x", role="Admin", is_active=True)
        second_admin = User(email="admin2@example.com", password_hash="x", role="Admin", is_active=True)
        inactive_admin = User(email="old-admin@example.com", password_hash="x", role="Admin", is_active=False)
        candidate = User(email="candidate@example.com", password_hash="x", role="Candidate", is_active=True)
        session.add_all([admin, second_admin, inactive_admin, candidate])
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def no_cache_get(_key):
        return None

    async def no_cache_set(_key, _value, ttl_seconds):
        return None

    app.dependency_overrides[get_db] = override_get_db
    # کش نشست کاربر (Redis) در این تست‌ها دخالتی ندارد — همیشه از دیتابیس خوانده شود
    monkeypatch.setattr(deps, "get_cached_json", no_cache_get)
    monkeypatch.setattr(deps, "set_cached_json", no_cache_set)
    monkeypatch.setattr(settings, "OPS_WEBHOOK_TOKEN", OPS_TOKEN)
    monkeypatch.setattr(settings, "OPS_ALERT_RECIPIENT_ROLES", "Admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {"client": client, "admin": admin, "candidate": candidate}

    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _user_auth(user: User) -> dict:
    access_token, _ = create_access_token(str(user.id))
    return _bearer(access_token)


@pytest.mark.asyncio
async def test_ops_endpoints_are_disabled_when_token_not_configured(env, monkeypatch):
    monkeypatch.setattr(settings, "OPS_WEBHOOK_TOKEN", "")
    response = await env["client"].post("/api/v1/ops/events", json={"title": "x"}, headers=_bearer("anything"))
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ops_endpoints_reject_missing_or_wrong_token(env):
    client = env["client"]
    assert (await client.post("/api/v1/ops/alerts", json=ALERTMANAGER_PAYLOAD)).status_code == 401
    response = await client.post("/api/v1/ops/alerts", json=ALERTMANAGER_PAYLOAD, headers=_bearer("wrong"))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_alert_is_delivered_only_to_active_tech_team(env):
    client = env["client"]

    response = await client.post("/api/v1/ops/alerts", json=ALERTMANAGER_PAYLOAD, headers=_bearer(OPS_TOKEN))
    assert response.status_code == 200
    # دو Admin فعال؛ Admin غیرفعال و Candidate نباید اعلان بگیرند
    assert response.json() == {"delivered_notifications": 2, "recipients": 2}

    admin_inbox = (await client.get("/api/v1/notifications/me", headers=_user_auth(env["admin"]))).json()
    assert admin_inbox["unread_count"] == 1
    notification = admin_inbox["items"][0]
    assert "HostHighMemoryUsage" in notification["title"]
    assert "CRITICAL" in notification["title"]
    assert "مصرف RAM سرور از ۸۵٪ عبور کرد" in notification["content"]
    assert notification["category"] == "alert"

    candidate_inbox = (await client.get("/api/v1/notifications/me", headers=_user_auth(env["candidate"]))).json()
    assert candidate_inbox["items"] == []
    assert candidate_inbox["unread_count"] == 0


@pytest.mark.asyncio
async def test_ci_event_report_and_mark_as_read(env):
    client = env["client"]
    admin_headers = _user_auth(env["admin"])

    response = await client.post(
        "/api/v1/ops/events",
        json={"title": "شکست خط لوله <script>alert(1)</script>", "content": "Tests: failure", "level": "failure"},
        headers=_bearer(OPS_TOKEN),
    )
    assert response.status_code == 200

    inbox = (await client.get("/api/v1/notifications/me", headers=admin_headers)).json()
    item = inbox["items"][0]
    assert item["title"].startswith("❌")
    assert "<script>" not in item["title"]  # دفاع XSS
    assert item["category"] == "deployment"

    read_response = await client.put(f"/api/v1/notifications/{item['id']}/read", headers=admin_headers)
    assert read_response.status_code == 200
    assert read_response.json()["is_read"] is True

    inbox = (await client.get("/api/v1/notifications/me", headers=admin_headers)).json()
    assert inbox["unread_count"] == 0


@pytest.mark.asyncio
async def test_user_cannot_mark_someone_elses_notification(env):
    client = env["client"]
    await client.post("/api/v1/ops/events", json={"title": "deploy ok"}, headers=_bearer(OPS_TOKEN))
    admin_inbox = (await client.get("/api/v1/notifications/me", headers=_user_auth(env["admin"]))).json()
    notification_id = admin_inbox["items"][0]["id"]

    response = await client.put(f"/api/v1/notifications/{notification_id}/read", headers=_user_auth(env["candidate"]))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mark_all_read(env):
    client = env["client"]
    for title in ("one", "two", "three"):
        await client.post("/api/v1/ops/events", json={"title": title}, headers=_bearer(OPS_TOKEN))

    admin_headers = _user_auth(env["admin"])
    response = await client.put("/api/v1/notifications/read-all", headers=admin_headers)
    assert response.json() == {"updated_count": 3}
    assert (await client.get("/api/v1/notifications/me", headers=admin_headers)).json()["unread_count"] == 0


def test_resolved_alert_message_format():
    alert = AlertmanagerAlert(
        status="resolved",
        labels={"alertname": "ApiHighErrorRate", "severity": "critical"},
        annotations={"summary": "نرخ خطاهای سرور (5xx) بالای ۵٪ است"},
        startsAt="2026-10-08T10:00:00Z",
        endsAt="2026-10-08T10:07:00Z",
    )
    title, content = format_alert_message(alert)
    assert title == "✅ [برطرف شد] ApiHighErrorRate"
    assert "پایان:" in content
