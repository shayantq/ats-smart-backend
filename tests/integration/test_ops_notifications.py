"""
تست کانال پیام‌رسان داخل سایت تیم فنی:
- وب‌هوک Alertmanager و گزارش CI/CD (app/routers/ops.py) فقط با توکن عملیاتی معتبر
  پذیرفته می‌شوند و بدون تنظیم توکن، کاملاً غیرفعال‌اند (503).
- هر پیام برای همه‌ی اعضای فعال تیم فنی (نقش Admin) — و فقط آن‌ها — اعلان می‌سازد.
- صندوق اعلان‌ها (app/routers/notifications.py) فقط اعلان‌های خودِ کاربر را نشان می‌دهد.

روی همان دیتابیس PostgreSQL موقت بقیه‌ی تست‌های یکپارچه‌سازی اجرا می‌شود (tests/integration/conftest.py).
"""

import pytest

from app.core.config import settings
from app.routers.ops import format_alert_message
from app.schemas.ops import AlertmanagerAlert
from tests.integration.conftest import auth_headers

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


@pytest.fixture
async def env(client, make_user, monkeypatch):
    admin = await make_user(role="Admin", email="admin@example.com")
    await make_user(role="Admin", email="admin2@example.com")
    await make_user(role="Admin", email="old-admin@example.com", is_active=False)
    candidate = await make_user(role="Candidate", email="candidate@example.com")

    monkeypatch.setattr(settings, "OPS_WEBHOOK_TOKEN", OPS_TOKEN)
    monkeypatch.setattr(settings, "OPS_ALERT_RECIPIENT_ROLES", "Admin")
    return {"client": client, "admin": admin, "candidate": candidate}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _user_auth(user) -> dict:
    return auth_headers(user)


async def test_ops_endpoints_are_disabled_when_token_not_configured(env, monkeypatch):
    monkeypatch.setattr(settings, "OPS_WEBHOOK_TOKEN", "")
    response = await env["client"].post("/api/v1/ops/events", json={"title": "x"}, headers=_bearer("anything"))
    assert response.status_code == 503


async def test_ops_endpoints_reject_missing_or_wrong_token(env):
    client = env["client"]
    assert (await client.post("/api/v1/ops/alerts", json=ALERTMANAGER_PAYLOAD)).status_code == 401
    response = await client.post("/api/v1/ops/alerts", json=ALERTMANAGER_PAYLOAD, headers=_bearer("wrong"))
    assert response.status_code == 401


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


async def test_user_cannot_mark_someone_elses_notification(env):
    client = env["client"]
    await client.post("/api/v1/ops/events", json={"title": "deploy ok"}, headers=_bearer(OPS_TOKEN))
    admin_inbox = (await client.get("/api/v1/notifications/me", headers=_user_auth(env["admin"]))).json()
    notification_id = admin_inbox["items"][0]["id"]

    response = await client.put(f"/api/v1/notifications/{notification_id}/read", headers=_user_auth(env["candidate"]))
    assert response.status_code == 404


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
