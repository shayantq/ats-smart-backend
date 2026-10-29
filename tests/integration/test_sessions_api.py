"""
تست یکپارچه‌ی مدیریت نشست‌ها — معیارهای پذیرش:

1. بعد از ابطال یک نشست توسط کاربر، Refresh Token آن فوراً در فهرست سیاه Redis است و نوسازی بعدی همان
   دستگاه → 401 (و access_token فعلی‌اش هم رد می‌شود).
2. GET /api/v1/auth/sessions/ جزئیات مرورگر و زمان آخرین فعالیت هر نشست را برمی‌گرداند.
3. ورود از مرورگر/IP تازه → کار ایمیل هشدار در صف Redis؛ ورود از کشوری دور → کار «Suspicious Login».

هر «دستگاه» یک AsyncClient جدا با IP و User-Agent خودش است. موقعیت جغرافیایی IP ها ثابت جایگزین شده.
"""

import time

import fakeredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from rq import Queue

from app.core import geoip, queue as queue_module, sessions
from app.core.config import settings
from app.core.geoip import GeoLocation
from app.core.queue import QUEUE_NOTIFICATIONS, enqueue_task
from app.core.security import create_refresh_token, decode_token
from app.main import app
from app.routers import auth as auth_router
from tests.integration.conftest import TEST_PASSWORD, auth_headers
from tests.unit.test_sessions import CHROME_WINDOWS, SAFARI_IPHONE

SESSIONS_URL = "/api/v1/auth/sessions/"
TEHRAN_IP, TEHRAN_OFFICE_IP, FRANKFURT_IP = "5.160.0.10", "5.160.0.20", "46.4.0.10"
LOCATIONS = {
    TEHRAN_IP: GeoLocation("IR", "Iran", "Tehran", 35.6892, 51.3890),
    TEHRAN_OFFICE_IP: GeoLocation("IR", "Iran", "Tehran", 35.7000, 51.4000),
    FRANKFURT_IP: GeoLocation("DE", "Germany", "Frankfurt am Main", 50.1109, 8.6821),
}


@pytest.fixture(autouse=True)
def fixed_geoip(monkeypatch):
    monkeypatch.setattr(geoip, "lookup", LOCATIONS.get)


@pytest_asyncio.fixture
async def device(client):
    """یک مرورگر روی یک دستگاه: IP و User-Agent ثابت (client فقط برای Override های مشترک تست)."""
    opened: list[AsyncClient] = []

    def _device(ip: str, user_agent: str) -> AsyncClient:
        http = AsyncClient(
            transport=ASGITransport(app=app, client=(ip, 50000)),
            base_url="http://test",
            headers={"User-Agent": user_agent},
        )
        opened.append(http)
        return http

    yield _device
    for http in opened:
        await http.aclose()


async def _login(http: AsyncClient, email: str) -> dict:
    response = await http.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_sessions_list_shows_browser_details_and_last_activity(device, make_user):
    user = await make_user(role="HR_Manager")
    laptop, phone = device(TEHRAN_IP, CHROME_WINDOWS), device(TEHRAN_OFFICE_IP, SAFARI_IPHONE)
    laptop_tokens = await _login(laptop, user.email)
    await _login(phone, user.email)

    response = await laptop.get(SESSIONS_URL, headers=_bearer(laptop_tokens))
    assert response.status_code == 200  # مسیر دقیق با «/» پایانی؛ بدون Redirect 307
    items = response.json()["items"]
    assert len(items) == 2

    by_browser = {item["browser"]: item for item in items}
    current, other = by_browser["Chrome"], by_browser["Mobile Safari"]
    assert current["is_current"] and not other["is_current"]
    assert (current["os"], current["device_type"], current["browser_version"]) == ("Windows", "desktop", "129.0.0")
    assert (other["os"], other["os_version"], other["device_type"]) == ("iOS", "17.5", "mobile")
    assert other["device"] == "Apple iPhone" and "iPhone" in other["user_agent"]
    assert current["ip"] == TEHRAN_IP and other["ip"] == "5.160.0.x"  # IP دستگاه‌های دیگر نیمه‌پنهان
    assert current["location"] == {"country": "Iran", "country_code": "IR", "city": "Tehran"}
    for item in items:
        assert item["last_active_at"] and item["created_at"] and item["expires_at"]
        assert item["suspicious"] is False
    assert items[0]["last_active_at"] >= items[1]["last_active_at"]  # جدیدترین فعالیت اول


async def test_revoked_session_cannot_refresh_and_is_sent_to_login(device, make_user, fake_redis):
    user = await make_user(role="Admin")
    laptop, stolen = device(TEHRAN_IP, CHROME_WINDOWS), device(TEHRAN_OFFICE_IP, SAFARI_IPHONE)
    laptop_tokens = await _login(laptop, user.email)
    stolen_tokens = await _login(stolen, user.email)

    items = (await laptop.get(SESSIONS_URL, headers=_bearer(laptop_tokens))).json()["items"]
    stolen_session = next(item for item in items if not item["is_current"])
    stolen_claims = decode_token(stolen_tokens["refresh_token"])
    assert stolen_session["id"] == stolen_claims["sid"]

    revoke = await laptop.delete(f"{SESSIONS_URL}{stolen_session['id']}/", headers=_bearer(laptop_tokens))
    assert revoke.status_code == 204

    # فهرست سیاه Redis: jti همان Refresh Token، با TTL تا پایان عمر توکن
    assert fake_redis.get(f"revoked_refresh:{stolen_claims['jti']}") == "revoked"
    assert 0 < fake_redis.ttl(f"revoked_refresh:{stolen_claims['jti']}") <= settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400

    # دستگاه باطل‌شده: نوسازی (کوکی) → 401 و پاک شدن کوکی؛ access_token فعلی‌اش هم دیگر پذیرفته نمیشود
    refresh = await stolen.post("/api/v1/auth/refresh", cookies={"refresh_token": stolen_tokens["refresh_token"]})
    assert refresh.status_code == 401
    assert 'refresh_token=""' in refresh.headers["set-cookie"] and "Max-Age=0" in refresh.headers["set-cookie"]
    assert (await stolen.get("/api/v1/auth/me", headers=_bearer(stolen_tokens))).status_code == 401

    # دستگاه خود کاربر دست نخورده است
    assert (await laptop.get("/api/v1/auth/me", headers=_bearer(laptop_tokens))).status_code == 200
    assert len((await laptop.get(SESSIONS_URL, headers=_bearer(laptop_tokens))).json()["items"]) == 1


async def test_refresh_rotates_token_and_reuse_kills_the_session(device, make_user, monkeypatch):
    user = await make_user(role="Candidate")
    browser = device(TEHRAN_IP, CHROME_WINDOWS)
    tokens = await _login(browser, user.email)

    rotated = await browser.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    new_refresh = rotated.json()["refresh_token"]
    assert new_refresh and new_refresh != tokens["refresh_token"]
    assert "refresh_token=" in rotated.headers["set-cookie"] and "HttpOnly" in rotated.headers["set-cookie"]
    assert (await browser.get("/api/v1/auth/me", headers=_bearer(rotated.json()))).status_code == 200

    # تب دوم همان مرورگر، هم‌زمان با همان کوکی قبلی: فقط access_token، بدون باطل شدن نشست
    duplicate = await browser.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert duplicate.status_code == 200 and duplicate.json()["refresh_token"] is None

    # بعد از بازه‌ی Grace: Replay توکن قدیمی (دزدیده‌شده) → کل نشست باطل، توکن جدید هم
    monkeypatch.setattr(sessions, "REFRESH_REUSE_GRACE_SECONDS", -1)
    replay = await browser.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    assert (await browser.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})).status_code == 401
    assert (await browser.get("/api/v1/auth/me", headers=_bearer(rotated.json()))).status_code == 401


async def test_invalid_refresh_tokens_are_rejected(client, make_user):
    user = await make_user(role="Candidate")
    legacy, _ = create_refresh_token(str(user.id))  # توکن Stateless قبل از مدیریت نشست، بدون sid
    access = auth_headers(user)["Authorization"].split()[1]

    for body in ({"refresh_token": legacy}, {"refresh_token": access}, {"refresh_token": "not-a-jwt"}, {}):
        response = await client.post("/api/v1/auth/refresh", json=body)
        assert response.status_code == 401, body
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_user_cannot_revoke_someone_elses_session(device, make_user):
    alice, bob = await make_user(role="Candidate"), await make_user(role="Candidate")
    alice_tokens = await _login(device(TEHRAN_IP, CHROME_WINDOWS), alice.email)
    bob_browser = device(TEHRAN_OFFICE_IP, SAFARI_IPHONE)
    bob_tokens = await _login(bob_browser, bob.email)
    bob_session = decode_token(bob_tokens["refresh_token"])["sid"]

    attack = await bob_browser.delete(f"{SESSIONS_URL}{bob_session}/", headers=_bearer(alice_tokens))
    assert attack.status_code == 404
    assert len((await bob_browser.get(SESSIONS_URL, headers=_bearer(bob_tokens))).json()["items"]) == 1
    assert (await bob_browser.get(SESSIONS_URL)).status_code == 401


async def test_logout_revokes_the_current_session(device, make_user):
    user = await make_user(role="Candidate")
    browser = device(TEHRAN_IP, CHROME_WINDOWS)
    tokens = await _login(browser, user.email)

    logout = await browser.post("/api/v1/auth/logout", headers=_bearer(tokens))
    assert logout.status_code == 204 and "Max-Age=0" in logout.headers["set-cookie"]
    assert (await browser.get("/api/v1/auth/me", headers=_bearer(tokens))).status_code == 401
    refresh = await browser.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


@pytest.fixture
def rq_redis(monkeypatch, fake_redis_server):
    """صف واقعی RQ روی Redis حافظه‌ای: کار ایمیل هشدار باید واقعاً در صف notifications بنشیند."""
    connection = fakeredis.FakeRedis(server=fake_redis_server)
    monkeypatch.setattr(queue_module, "_get_sync_redis_client", lambda: connection)
    monkeypatch.setattr(queue_module, "_task_queues", {})
    monkeypatch.setattr(auth_router, "enqueue_task", enqueue_task)
    return connection


def _queued_alerts(connection) -> list:
    return [
        job
        for job in Queue(QUEUE_NOTIFICATIONS, connection=connection).get_jobs()
        if job.func_name.endswith("_login_email_task") or job.func_name.endswith("_signin_email_task")
    ]


async def test_login_from_new_browser_or_ip_enqueues_security_email(device, make_user, rq_redis):
    user = await make_user(role="HR_Manager")

    await _login(device(TEHRAN_IP, CHROME_WINDOWS), user.email)
    assert _queued_alerts(rq_redis) == []  # اولین ورود: دستگاهی برای مقایسه نیست
    await _login(device(TEHRAN_IP, CHROME_WINDOWS), user.email)
    assert _queued_alerts(rq_redis) == []  # همان مرورگر و IP

    await _login(device(TEHRAN_OFFICE_IP, SAFARI_IPHONE), user.email)
    jobs = _queued_alerts(rq_redis)
    assert [job.func_name for job in jobs] == ["app.tasks.notifications.send_new_signin_email_task"]
    to_email, details = jobs[0].args
    assert to_email == user.email
    assert details["browser"] == "Mobile Safari 17.5" and details["os"] == "iOS 17.5"
    assert details["ip"] == TEHRAN_OFFICE_IP and details["location"] == "Tehran، Iran"
    assert details["sessions_url"].endswith("/?view=sessions")


async def test_login_from_far_away_country_enqueues_suspicious_login_email(device, make_user, rq_redis):
    user = await make_user(role="Admin")
    await _login(device(TEHRAN_IP, CHROME_WINDOWS), user.email)

    attacker = device(FRANKFURT_IP, CHROME_WINDOWS)
    attacker_tokens = await _login(attacker, user.email)

    jobs = _queued_alerts(rq_redis)
    assert [job.func_name for job in jobs] == ["app.tasks.notifications.send_suspicious_login_email_task"]
    to_email, details, reasons = jobs[0].args
    assert to_email == user.email and details["location"] == "Frankfurt am Main، Germany"
    assert any("Germany" in reason for reason in reasons)
    assert any("جابه‌جایی ناممکن" in reason for reason in reasons)

    flagged = (await attacker.get(SESSIONS_URL, headers=_bearer(attacker_tokens))).json()["items"]
    assert {item["location"]["city"]: item["suspicious"] for item in flagged} == {
        "Frankfurt am Main": True,
        "Tehran": False,
    }


async def test_login_still_works_without_geoip_or_queue(device, make_user, monkeypatch):
    """GeoIP ناموجود و صف Redis ازکارافتاده: ورود موفق، فقط هشدار جغرافیایی/ایمیل انجام نمی‌شود."""
    monkeypatch.setattr(geoip, "lookup", lambda ip: None)

    async def broken_enqueue(*args, **kwargs):
        return None  # همان رفتار enqueue_task هنگام قطعی Redis صف

    monkeypatch.setattr(auth_router, "enqueue_task", broken_enqueue)
    user = await make_user(role="Candidate")
    started = time.monotonic()
    tokens = await _login(device(TEHRAN_IP, CHROME_WINDOWS), user.email)
    await _login(device(FRANKFURT_IP, SAFARI_IPHONE), user.email)
    assert time.monotonic() - started < 10
    assert tokens["access_token"]


async def test_session_store_outage_fails_closed(client, make_user, monkeypatch):
    user = await make_user(role="Candidate")
    headers = auth_headers(user)
    server = fakeredis.FakeServer()
    server.connected = False
    monkeypatch.setattr(sessions, "get_redis_client", lambda: fakeredis.FakeAsyncRedis(server=server))

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 503
    login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert login.status_code == 503


async def test_admin_manages_sessions_only_inside_own_tenant(client, device, make_user, make_tenant):
    org_a, admin_a = await make_tenant("Org A")
    _, admin_b = await make_tenant("Org B")
    hr = await make_user(role="HR_Manager", tenant=org_a)
    hr_browser = device(TEHRAN_IP, CHROME_WINDOWS)
    hr_tokens = await _login(hr_browser, hr.email)
    await _login(device(TEHRAN_OFFICE_IP, SAFARI_IPHONE), hr.email)
    url = f"/api/v1/admin/users/{hr.id}/sessions/"

    listed = await client.get(url, headers=auth_headers(admin_a))
    assert listed.status_code == 200 and len(listed.json()["items"]) == 2
    assert {item["ip"] for item in listed.json()["items"]} == {TEHRAN_IP, TEHRAN_OFFICE_IP}  # Admin: IP کامل

    # Admin سازمان دیگر، و HR بدون نقش Admin
    assert (await client.get(url, headers=auth_headers(admin_b))).status_code == 404
    assert (await client.delete(url, headers=auth_headers(admin_b))).status_code == 404
    assert (await client.get(url, headers=_bearer(hr_tokens))).status_code == 403

    one = listed.json()["items"][0]["id"]
    assert (await client.delete(f"{url}{one}/", headers=auth_headers(admin_b))).status_code == 404
    assert (await client.delete(f"{url}{one}/", headers=auth_headers(admin_a))).status_code == 204

    revoke_all = await client.delete(url, headers=auth_headers(admin_a))
    assert revoke_all.status_code == 200 and revoke_all.json() == {"revoked": 1}
    refresh = await hr_browser.post("/api/v1/auth/refresh", json={"refresh_token": hr_tokens["refresh_token"]})
    assert refresh.status_code == 401
    assert (await hr_browser.get("/api/v1/auth/me", headers=_bearer(hr_tokens))).status_code == 401
