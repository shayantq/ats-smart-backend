"""
تست واحد مدیریت نشست‌ها (app/core/sessions.py) و موقعیت جغرافیایی (app/core/geoip.py):
تشخیص مرورگر/سیستم‌عامل، اثر انگشت دستگاه، قواعد ورود مشکوک، نبود دیتابیس GeoIP، و چرخه‌ی عمر نشست
روی یک Redis حافظه‌ای (ساخت، چرخش Refresh Token، استفاده‌ی دوباره، ابطال، آخرین فعالیت).
"""

import json
import time

import fakeredis
import pytest

from app.core import geoip, sessions
from app.core.config import settings
from app.core.geoip import GeoLocation

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Mobile/15E148 Safari/604.1"
)
SAFARI_IPAD = (
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Mobile/15E148 Safari/604.1"
)
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

TEHRAN = GeoLocation("IR", "Iran", "Tehran", 35.6892, 51.3890)
KARAJ = GeoLocation("IR", "Iran", "Karaj", 35.8400, 50.9391)
MASHHAD = GeoLocation("IR", "Iran", "Mashhad", 36.2605, 59.6168)
FRANKFURT = GeoLocation("DE", "Germany", "Frankfurt am Main", 50.1109, 8.6821)


def _history(geo: GeoLocation, seconds_ago: float, now: float) -> list[dict]:
    return [{"ts": now - seconds_ago, "country_code": geo.country_code, "lat": geo.latitude, "lon": geo.longitude}]


# ---------------------------------------------------------------------------
# مرورگر، دستگاه و IP
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("user_agent", "browser", "os", "device_type"),
    [
        (CHROME_WINDOWS, "Chrome", "Windows", "desktop"),
        (SAFARI_IPHONE, "Mobile Safari", "iOS", "mobile"),
        (SAFARI_IPAD, "Mobile Safari", "iOS", "tablet"),
        (GOOGLEBOT, "Googlebot", "Other", "bot"),
        (None, "Other", "Other", "other"),
    ],
)
def test_user_agent_is_parsed_into_browser_os_and_device_type(user_agent, browser, os, device_type):
    device = sessions.parse_user_agent(user_agent)

    assert (device.browser, device.os, device.device_type) == (browser, os, device_type)
    assert device.fingerprint == f"{browser}|{os}"


def test_browser_and_os_versions_are_kept():
    device = sessions.parse_user_agent(SAFARI_IPHONE)

    assert device.browser_version == "17.5" and device.os_version == "17.5"
    assert device.device == "Apple iPhone"


def test_ip_masking():
    assert sessions.mask_ip("5.160.12.34") == "5.160.12.x"
    assert sessions.mask_ip("2a01:4f8:1c1c:abcd::1") == "2a01:4f8:1c1c:x"
    assert sessions.mask_ip(None) == ""


# ---------------------------------------------------------------------------
# دستگاه جدید و ورود مشکوک
# ---------------------------------------------------------------------------
def test_first_login_ever_raises_no_alert():
    device = sessions.parse_user_agent(CHROME_WINDOWS)
    assessment = sessions.assess_login(set(), [], device, "5.160.0.10", TEHRAN, time.time())

    assert assessment.first_login and not assessment.should_alert_new_device and not assessment.suspicious


def test_known_browser_and_ip_raise_no_alert_but_new_ones_do():
    now = time.time()
    device = sessions.parse_user_agent(CHROME_WINDOWS)
    known = {f"ua:{device.fingerprint}", "ip:5.160.0.10"}
    history = _history(TEHRAN, 3600, now)

    assert not sessions.assess_login(known, history, device, "5.160.0.10", TEHRAN, now).should_alert_new_device

    new_ip = sessions.assess_login(known, history, device, "5.160.0.99", TEHRAN, now)
    assert new_ip.new_ip and not new_ip.new_device and new_ip.should_alert_new_device

    phone = sessions.assess_login(known, history, sessions.parse_user_agent(SAFARI_IPHONE), "5.160.0.10", TEHRAN, now)
    assert phone.new_device and phone.should_alert_new_device


def test_login_from_a_new_country_is_suspicious():
    now = time.time()
    reasons = sessions.detect_anomaly(_history(TEHRAN, 30 * 24 * 3600, now), FRANKFURT, now)

    assert any("Germany" in reason for reason in reasons)


def test_impossible_travel_inside_the_same_country_is_suspicious():
    now = time.time()
    # تهران → مشهد (~۷۴۰ کیلومتر) در ۳۰ دقیقه ≈ ۱۵۰۰ کیلومتر بر ساعت
    reasons = sessions.detect_anomaly(_history(TEHRAN, 30 * 60, now), MASHHAD, now)

    assert len(reasons) == 1 and "جابه‌جایی ناممکن" in reasons[0]


@pytest.mark.parametrize(
    ("previous", "current", "seconds_ago"),
    [
        (TEHRAN, MASHHAD, 5 * 3600),  # همان فاصله در ۵ ساعت: پرواز داخلی، عادی
        (TEHRAN, KARAJ, 60),  # ~۴۰ کیلومتر: زیر آستانه‌ی فاصله، حتی در یک دقیقه
        (TEHRAN, TEHRAN, 10),
    ],
)
def test_plausible_movement_is_not_suspicious(previous, current, seconds_ago):
    now = time.time()
    assert sessions.detect_anomaly(_history(previous, seconds_ago, now), current, now) == []


def test_unknown_location_or_missing_history_skips_geo_rules():
    now = time.time()
    assert sessions.detect_anomaly(_history(TEHRAN, 60, now), None, now) == []
    assert sessions.detect_anomaly([], FRANKFURT, now) == []
    # ورودهای قبلی بدون موقعیت (IP خصوصی/نبود دیتابیس) → کشور «شناخته‌شده‌ای» برای مقایسه نیست
    assert sessions.detect_anomaly([{"ts": now - 60, "country_code": None}], FRANKFURT, now) == []


def test_thresholds_come_from_settings(monkeypatch):
    now = time.time()
    monkeypatch.setattr(settings, "SUSPICIOUS_LOGIN_DISTANCE_KM", 10_000.0)
    assert sessions.detect_anomaly(_history(TEHRAN, 30 * 60, now), MASHHAD, now) == []


def test_haversine_distance():
    distance = geoip.haversine_km(TEHRAN.latitude, TEHRAN.longitude, FRANKFURT.latitude, FRANKFURT.longitude)
    assert 3_700 < distance < 3_850  # ~۳۷۶۵ کیلومتر


# ---------------------------------------------------------------------------
# GeoIP: نبود دیتابیس یا IP خصوصی هرگز ورود را از کار نمی‌اندازد
# ---------------------------------------------------------------------------
def test_geoip_without_database_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "GEOIP_DB_PATH", str(tmp_path / "missing.mmdb"))
    geoip.reset_reader_cache()
    try:
        assert geoip.lookup("8.8.8.8") is None
    finally:
        geoip.reset_reader_cache()


def test_corrupt_geoip_database_returns_none(monkeypatch, tmp_path):
    corrupt = tmp_path / "corrupt.mmdb"
    corrupt.write_bytes(b"not a database")
    monkeypatch.setattr(settings, "GEOIP_DB_PATH", str(corrupt))
    geoip.reset_reader_cache()
    try:
        assert geoip.lookup("8.8.8.8") is None
    finally:
        geoip.reset_reader_cache()


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "172.18.0.3", "192.168.1.1", "::1", "not-an-ip", None])
def test_private_or_invalid_ips_are_not_looked_up(ip):
    assert not geoip.is_public_ip(ip)
    assert geoip.lookup(ip) is None


# ---------------------------------------------------------------------------
# چرخه‌ی عمر نشست روی Redis
# ---------------------------------------------------------------------------
@pytest.fixture
def redis(monkeypatch):
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    monkeypatch.setattr(sessions, "get_redis_client", lambda: client)
    monkeypatch.setattr(sessions.geoip, "lookup", lambda ip: {"5.160.0.10": TEHRAN, "46.4.0.10": FRANKFURT}.get(ip))
    return client


async def _login(ip="5.160.0.10", user_agent=CHROME_WINDOWS, user_id="user-1"):
    return await sessions.create_session(user_id=user_id, tenant_id=None, ip=ip, user_agent=user_agent)


async def test_session_metadata_and_ttls_are_stored(redis):
    created = await _login()
    stored = await redis.hgetall(f"session:{created.session_id}")

    assert stored["ip"] == "5.160.0.10" and stored["browser"] == "Chrome" and stored["os"] == "Windows"
    assert stored["city"] == "Tehran" and stored["refresh_jti"] == created.refresh_jti
    lifetime = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    for key in (f"session:{created.session_id}", "user_sessions:user-1"):
        assert 0 < await redis.ttl(key) <= lifetime
    for key in ("user_known_devices:user-1", "user_login_history:user-1"):
        assert 0 < await redis.ttl(key) <= sessions.KNOWN_DEVICES_TTL_SECONDS


async def test_login_history_and_known_devices_are_capped(redis):
    for index in range(sessions.LOGIN_HISTORY_MAX + 5):
        await _login(ip=f"5.160.1.{index}")

    assert await redis.llen("user_login_history:user-1") == sessions.LOGIN_HISTORY_MAX
    history = [json.loads(item) for item in await redis.lrange("user_login_history:user-1", 0, -1)]
    assert history[0]["ip"] == f"5.160.1.{sessions.LOGIN_HISTORY_MAX + 4}"  # جدیدترین اول
    assert await redis.zcard("user_known_devices:user-1") <= sessions.KNOWN_DEVICES_MAX


async def test_second_login_from_far_country_is_flagged(redis):
    await _login(ip="5.160.0.10")
    created = await _login(ip="46.4.0.10")

    assert created.assessment.suspicious and created.data["suspicious"] == "1"


async def test_refresh_rotation_blacklists_previous_jti(redis):
    created = await _login()
    outcome = await sessions.rotate_refresh(session_id=created.session_id, jti=created.refresh_jti, user_id="user-1")

    assert outcome.new_refresh_jti and outcome.new_refresh_jti != created.refresh_jti
    assert await redis.get(f"revoked_refresh:{created.refresh_jti}") == "rotated"
    assert 0 < await redis.ttl(f"revoked_refresh:{created.refresh_jti}")


async def test_concurrent_refresh_within_grace_gets_access_only(redis):
    created = await _login()
    await sessions.rotate_refresh(session_id=created.session_id, jti=created.refresh_jti, user_id="user-1")

    duplicate = await sessions.rotate_refresh(session_id=created.session_id, jti=created.refresh_jti, user_id="user-1")
    assert duplicate.new_refresh_jti is None
    assert await redis.exists(f"session:{created.session_id}")


async def test_reusing_an_old_refresh_token_revokes_the_whole_session(redis, monkeypatch):
    monkeypatch.setattr(sessions, "REFRESH_REUSE_GRACE_SECONDS", -1)
    created = await _login()
    rotated = await sessions.rotate_refresh(session_id=created.session_id, jti=created.refresh_jti, user_id="user-1")

    with pytest.raises(sessions.SessionInvalid) as error:
        await sessions.rotate_refresh(session_id=created.session_id, jti=created.refresh_jti, user_id="user-1")
    assert error.value.reason == "refresh_token_reuse"
    assert not await redis.exists(f"session:{created.session_id}")
    assert await redis.exists(f"revoked_refresh:{rotated.new_refresh_jti}")  # توکن جدید (دست مهاجم) هم باطل
    with pytest.raises(sessions.SessionInvalid):
        await sessions.rotate_refresh(session_id=created.session_id, jti=rotated.new_refresh_jti, user_id="user-1")


async def test_refresh_for_another_user_or_unknown_session_is_rejected(redis):
    created = await _login()
    with pytest.raises(sessions.SessionInvalid):
        await sessions.rotate_refresh(session_id=created.session_id, jti=created.refresh_jti, user_id="user-2")
    with pytest.raises(sessions.SessionInvalid):
        await sessions.rotate_refresh(session_id="missing", jti=created.refresh_jti, user_id="user-1")


async def test_revoke_blacklists_refresh_and_removes_session(redis):
    created = await _login()

    assert not await sessions.revoke_session(created.session_id, user_id="user-2")  # نشست کاربر دیگر
    assert await sessions.revoke_session(created.session_id, user_id="user-1")
    assert await redis.get(f"revoked_refresh:{created.refresh_jti}") == "revoked"
    assert await sessions.list_sessions("user-1") == []
    assert not await sessions.touch_session(created.session_id)


async def test_last_activity_is_throttled(redis, monkeypatch):
    created = await _login()
    clock = [time.time() + 120]
    monkeypatch.setattr(sessions.time, "time", lambda: clock[0])

    assert await sessions.touch_session(created.session_id)
    first = (await sessions.list_sessions("user-1"))[0]["last_active_at"]
    clock[0] += 30  # داخل بازه‌ی ۶۰ ثانیه‌ای: نوشتنی انجام نمی‌شود
    assert await sessions.touch_session(created.session_id)
    assert (await sessions.list_sessions("user-1"))[0]["last_active_at"] == first
    assert float(first) == pytest.approx(clock[0] - 30)


async def test_expired_sessions_are_pruned_from_the_index(redis):
    created = await _login()
    await redis.delete(f"session:{created.session_id}")  # TTL تمام شد

    assert await sessions.list_sessions("user-1") == []
    assert await redis.zcard("user_sessions:user-1") == 0


async def test_redis_outage_fails_closed(monkeypatch):
    server = fakeredis.FakeServer()
    server.connected = False  # هر فرمان → ConnectionError
    broken = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    monkeypatch.setattr(sessions, "get_redis_client", lambda: broken)

    with pytest.raises(sessions.SessionStoreUnavailable):
        await sessions.touch_session("any")
    with pytest.raises(sessions.SessionStoreUnavailable):
        await _login()
