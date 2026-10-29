"""
مدیریت نشست‌های کاربر (Session Management) — Refresh Token دیگر کاملاً Stateless نیست.

هر ورود یک نشست در Redis می‌سازد و Refresh Token فقط تا وقتی معتبر است که نشستش وجود داشته باشد و
jti آن همان jti فعلی نشست باشد. کاربر (یا Admin سازمان) هر نشست را می‌تواند فوراً باطل کند.

کلیدهای Redis (همه TTL دارند؛ هیچ‌کدام بی‌حد رشد نمی‌کنند):
    session:{sid}                 Hash — متادیتای نشست: کاربر، IP، User-Agent، مرورگر، سیستم‌عامل، موقعیت،
                                  زمان ساخت و آخرین فعالیت، jti فعلی/قبلی Refresh Token. TTL = عمر Refresh Token
    user_sessions:{user_id}       Sorted Set — شناسه‌ی نشست‌های فعال کاربر، امتیاز = زمان آخرین فعالیت
    revoked_refresh:{jti}         فهرست سیاه — jti های باطل/چرخیده تا پایان عمر خود توکن
    session_touch:{sid}           قفل ۶۰ ثانیه‌ای ثبت آخرین فعالیت (هر درخواست یک نوشتن نمی‌شود)
    user_known_devices:{user_id}  Sorted Set — اثر انگشت دستگاه‌ها (ua:مرورگر|سیستم‌عامل) و IP های شناخته‌شده، ۹۰ روز
    user_login_history:{user_id}  List — ۲۰ ورود اخیر (زمان، کشور، مختصات) برای تشخیص ورود مشکوک، ۹۰ روز

جریان‌ها و الگوریتم تشخیص ناهنجاری: docs/sessions/ARCHITECTURE.md
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache

from redis.exceptions import RedisError, WatchError
from user_agents import parse as parse_ua

from app.core import geoip
from app.core.config import settings
from app.core.redis_client import get_redis_client

logger = logging.getLogger("ats_smart.sessions")

SESSION_KEY_PREFIX = "session:"
USER_SESSIONS_KEY_PREFIX = "user_sessions:"
REVOKED_REFRESH_KEY_PREFIX = "revoked_refresh:"
SESSION_TOUCH_KEY_PREFIX = "session_touch:"
KNOWN_DEVICES_KEY_PREFIX = "user_known_devices:"
LOGIN_HISTORY_KEY_PREFIX = "user_login_history:"

KNOWN_DEVICES_TTL_SECONDS = 90 * 24 * 3600
KNOWN_DEVICES_MAX = 50
LOGIN_HISTORY_MAX = 20
ACTIVITY_THROTTLE_SECONDS = 60
# دو تب یک مرورگر هم‌زمان با یک کوکی نوسازی می‌کنند: درخواست دوم jti قبلی را می‌فرستد. در این چند
# ثانیه فقط access_token تازه می‌گیرد (کوکی را تب اول عوض کرده)؛ بعد از آن، استفاده از jti قبلی =
# سرقت توکن → کل نشست باطل می‌شود.
REFRESH_REUSE_GRACE_SECONDS = 10
_MAX_ROTATION_ATTEMPTS = 3


class SessionStoreUnavailable(Exception):
    """Redis در دسترس نیست؛ احراز هویت «بسته» شکست می‌خورد (503)، نه این‌که نشست باطل‌شده پذیرفته شود."""


class SessionInvalid(Exception):
    """نشست وجود ندارد، باطل شده، یا Refresh Token دوباره استفاده شده است (401)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _user_sessions_key(user_id: str) -> str:
    return f"{USER_SESSIONS_KEY_PREFIX}{user_id}"


def _revoked_key(jti: str) -> str:
    return f"{REVOKED_REFRESH_KEY_PREFIX}{jti}"


def _refresh_lifetime_seconds() -> int:
    return settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600


# ---------------------------------------------------------------------------
# مرورگر و دستگاه
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DeviceInfo:
    browser: str
    browser_version: str
    os: str
    os_version: str
    device_type: str
    device: str

    @property
    def fingerprint(self) -> str:
        return f"{self.browser}|{self.os}"


@lru_cache(maxsize=1024)
def parse_user_agent(user_agent: str | None) -> DeviceInfo:
    ua = parse_ua(user_agent or "")
    if ua.is_bot:
        device_type = "bot"
    elif ua.is_tablet:
        device_type = "tablet"
    elif ua.is_mobile:
        device_type = "mobile"
    elif ua.is_pc:
        device_type = "desktop"
    else:
        device_type = "other"
    device = " ".join(part for part in (ua.device.brand, ua.device.model) if part) or ""
    return DeviceInfo(
        browser=ua.browser.family or "Other",
        browser_version=ua.browser.version_string or "",
        os=ua.os.family or "Other",
        os_version=ua.os.version_string or "",
        device_type=device_type,
        device=device,
    )


def mask_ip(ip: str | None) -> str:
    """IP نشست‌های دیگر در فهرست نیمه‌پنهان نمایش داده می‌شود (۱.۲.۳.x)."""
    if not ip:
        return ""
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + ":x"
    parts = ip.split(".")
    return ".".join(parts[:3] + ["x"]) if len(parts) == 4 else ip


# ---------------------------------------------------------------------------
# تشخیص دستگاه جدید و ورود مشکوک (توابع خالص — بدون Redis، قابل تست واحد)
# ---------------------------------------------------------------------------
@dataclass
class LoginAssessment:
    first_login: bool = False
    new_device: bool = False
    new_ip: bool = False
    suspicious: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def should_alert_new_device(self) -> bool:
        return not self.first_login and not self.suspicious and (self.new_device or self.new_ip)


def detect_anomaly(
    history: list[dict],
    geo: geoip.GeoLocation | None,
    now: float,
    distance_km: float | None = None,
    speed_kmh: float | None = None,
) -> list[str]:
    """
    دلایل مشکوک بودن ورود (فهرست خالی = عادی):
      ۱. کشور ورود با هیچ‌کدام از کشورهای ورودهای قبلی یکی نیست.
      ۲. «سفر ناممکن»: فاصله از آخرین ورودِ دارای مختصات بیش از distance_km و سرعت لازم برای طی آن
         در فاصله‌ی زمانی دو ورود بیش از speed_kmh.
    موقعیت نامعلوم (IP خصوصی، نبود دیتابیس GeoIP) یا نبود سابقه‌ی جغرافیایی → هیچ قاعده‌ای اعمال نمی‌شود.
    """
    distance_km = settings.SUSPICIOUS_LOGIN_DISTANCE_KM if distance_km is None else distance_km
    speed_kmh = settings.SUSPICIOUS_LOGIN_SPEED_KMH if speed_kmh is None else speed_kmh
    if geo is None:
        return []
    reasons: list[str] = []

    known_countries = {entry["country_code"] for entry in history if entry.get("country_code")}
    if geo.country_code and known_countries and geo.country_code not in known_countries:
        reasons.append(f"ورود از کشوری که پیش‌تر از آن وارد نشده بودید ({geo.country or geo.country_code})")

    previous = next((entry for entry in history if entry.get("lat") is not None and entry.get("lon") is not None), None)
    if geo.has_coordinates and previous is not None:
        distance = geoip.haversine_km(previous["lat"], previous["lon"], geo.latitude, geo.longitude)
        hours = max(now - float(previous["ts"]), 60.0) / 3600
        if distance > distance_km and distance / hours > speed_kmh:
            reasons.append(f"جابه‌جایی ناممکن: {distance:,.0f} کیلومتر از ورود قبلی در {hours * 60:,.0f} دقیقه")
    return reasons


def assess_login(
    known_members: set[str], history: list[dict], device: DeviceInfo, ip: str, geo: geoip.GeoLocation | None, now: float
) -> LoginAssessment:
    first_login = not known_members and not history
    reasons = [] if first_login else detect_anomaly(history, geo, now)
    return LoginAssessment(
        first_login=first_login,
        new_device=f"ua:{device.fingerprint}" not in known_members,
        new_ip=bool(ip) and f"ip:{ip}" not in known_members,
        suspicious=bool(reasons),
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# چرخه‌ی عمر نشست در Redis
# ---------------------------------------------------------------------------
@dataclass
class CreatedSession:
    session_id: str
    refresh_jti: str
    data: dict
    assessment: LoginAssessment
    geo: geoip.GeoLocation | None


async def create_session(*, user_id: str, tenant_id: str | None, ip: str, user_agent: str | None) -> CreatedSession:
    device = parse_user_agent(user_agent)
    geo = geoip.lookup(ip)
    now = time.time()
    lifetime = _refresh_lifetime_seconds()
    session_id, refresh_jti = str(uuid.uuid4()), uuid.uuid4().hex
    known_key, history_key = f"{KNOWN_DEVICES_KEY_PREFIX}{user_id}", f"{LOGIN_HISTORY_KEY_PREFIX}{user_id}"

    data = {
        "sid": session_id,
        "user_id": user_id,
        "tenant_id": tenant_id or "",
        "ip": ip or "",
        "user_agent": (user_agent or "")[:512],
        "browser": device.browser,
        "browser_version": device.browser_version,
        "os": device.os,
        "os_version": device.os_version,
        "device_type": device.device_type,
        "device": device.device,
        "country_code": (geo.country_code if geo else None) or "",
        "country": (geo.country if geo else None) or "",
        "city": (geo.city if geo else None) or "",
        "lat": "" if not (geo and geo.has_coordinates) else str(geo.latitude),
        "lon": "" if not (geo and geo.has_coordinates) else str(geo.longitude),
        "created_at": str(now),
        "last_active_at": str(now),
        "expires_at": str(now + lifetime),
        "refresh_jti": refresh_jti,
        "previous_jti": "",
        "rotated_at": "",
        "suspicious": "0",
    }

    client = get_redis_client()
    try:
        async with client.pipeline(transaction=False) as pipe:
            pipe.zrange(known_key, 0, -1)
            pipe.lrange(history_key, 0, -1)
            known_members, raw_history = await pipe.execute()
        history = [json.loads(item) for item in raw_history]
        assessment = assess_login(set(known_members), history, device, ip, geo, now)
        data["suspicious"] = "1" if assessment.suspicious else "0"

        history_entry = {"ts": now, "ip": ip, "country_code": data["country_code"] or None}
        if geo and geo.has_coordinates:
            history_entry.update(lat=geo.latitude, lon=geo.longitude)
        known = {f"ua:{device.fingerprint}": now}
        if ip:
            known[f"ip:{ip}"] = now

        async with client.pipeline(transaction=True) as pipe:
            pipe.hset(_session_key(session_id), mapping=data)
            pipe.expire(_session_key(session_id), lifetime)
            pipe.zadd(_user_sessions_key(user_id), {session_id: now})
            pipe.zremrangebyscore(_user_sessions_key(user_id), "-inf", now - lifetime)
            pipe.expire(_user_sessions_key(user_id), lifetime)
            pipe.zadd(known_key, known)
            pipe.zremrangebyrank(known_key, 0, -(KNOWN_DEVICES_MAX + 1))
            pipe.expire(known_key, KNOWN_DEVICES_TTL_SECONDS)
            pipe.lpush(history_key, json.dumps(history_entry))
            pipe.ltrim(history_key, 0, LOGIN_HISTORY_MAX - 1)
            pipe.expire(history_key, KNOWN_DEVICES_TTL_SECONDS)
            await pipe.execute()
    except RedisError as error:
        logger.error("ساخت نشست در Redis ناموفق بود: %s", error)
        raise SessionStoreUnavailable from error

    return CreatedSession(session_id, refresh_jti, data, assessment, geo)


@dataclass
class RefreshOutcome:
    data: dict
    # None: درخواست هم‌زمان تب دیگر در بازه‌ی Grace — فقط access_token تازه، کوکی عوض نمی‌شود
    new_refresh_jti: str | None


async def rotate_refresh(*, session_id: str, jti: str, user_id: str) -> RefreshOutcome:
    """
    نوسازی با چرخش Refresh Token: jti فعلی در فهرست سیاه می‌رود و jti تازه صادر می‌شود.
    jti قبلی بعد از بازه‌ی Grace (Replay توکن دزدیده‌شده) → کل نشست باطل می‌شود.
    مقایسه و جایگزینی jti با WATCH/MULTI اتمیک است: دو درخواست هم‌زمان هر دو برنده نمی‌شوند.
    """
    client = get_redis_client()
    key = _session_key(session_id)
    lifetime = _refresh_lifetime_seconds()
    try:
        for _ in range(_MAX_ROTATION_ATTEMPTS):
            async with client.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                data = await pipe.hgetall(key)
                blacklisted = bool(await pipe.exists(_revoked_key(jti)))
                now = time.time()
                if not data or data.get("user_id") != user_id:
                    raise SessionInvalid("revoked" if blacklisted else "unknown_session")

                if jti == data.get("previous_jti") and data.get("rotated_at"):
                    if now - float(data["rotated_at"]) <= REFRESH_REUSE_GRACE_SECONDS:
                        await pipe.unwatch()
                        return RefreshOutcome(data, None)
                if jti != data.get("refresh_jti") or blacklisted:
                    await pipe.unwatch()
                    await revoke_session(session_id)
                    logger.warning("استفاده‌ی دوباره از Refresh Token — نشست %s باطل شد", session_id)
                    raise SessionInvalid("refresh_token_reuse")

                new_jti = uuid.uuid4().hex
                remaining = max(int(float(data["expires_at"]) - now), 1)
                update = {
                    "refresh_jti": new_jti,
                    "previous_jti": jti,
                    "rotated_at": str(now),
                    "last_active_at": str(now),
                    "expires_at": str(now + lifetime),
                }
                pipe.multi()
                pipe.hset(key, mapping=update)
                pipe.expire(key, lifetime)
                pipe.set(_revoked_key(jti), "rotated", ex=remaining)
                pipe.zadd(_user_sessions_key(user_id), {session_id: now})
                pipe.expire(_user_sessions_key(user_id), lifetime)
                try:
                    await pipe.execute()
                except WatchError:
                    continue  # نشست هم‌زمان عوض شد؛ دوباره با داده‌ی تازه تصمیم گرفته می‌شود
                return RefreshOutcome({**data, **update}, new_jti)
    except RedisError as error:
        logger.error("نوسازی نشست در Redis ناموفق بود: %s", error)
        raise SessionStoreUnavailable from error
    raise SessionInvalid("concurrent_rotation")


async def revoke_session(session_id: str, *, user_id: str | None = None) -> bool:
    """
    ابطال فوری: jti فعلی Refresh Token تا پایان عمرش در فهرست سیاه، نشست و ردیفش در فهرست کاربر حذف.
    user_id داده شود → فقط نشست همان کاربر (نشست کاربر دیگر = «وجود ندارد»).
    """
    client = get_redis_client()
    key = _session_key(session_id)
    try:
        data = await client.hgetall(key)
        if not data or (user_id is not None and data.get("user_id") != user_id):
            return False
        remaining = max(int(float(data.get("expires_at") or 0) - time.time()), 1)
        async with client.pipeline(transaction=True) as pipe:
            pipe.set(_revoked_key(data["refresh_jti"]), "revoked", ex=remaining)
            pipe.delete(key, f"{SESSION_TOUCH_KEY_PREFIX}{session_id}")
            pipe.zrem(_user_sessions_key(data["user_id"]), session_id)
            await pipe.execute()
    except RedisError as error:
        logger.error("ابطال نشست در Redis ناموفق بود: %s", error)
        raise SessionStoreUnavailable from error
    return True


async def revoke_all_sessions(user_id: str) -> int:
    revoked = 0
    for session in await list_sessions(user_id):
        revoked += await revoke_session(session["sid"], user_id=user_id)
    return revoked


async def list_sessions(user_id: str) -> list[dict]:
    """نشست‌های فعال کاربر، جدیدترین فعالیت اول. ردیف نشست‌هایی که TTL شان تمام شده پاک می‌شود."""
    client = get_redis_client()
    index_key = _user_sessions_key(user_id)
    try:
        indexed = await client.zrevrange(index_key, 0, -1, withscores=True)
        if not indexed:
            return []
        async with client.pipeline(transaction=False) as pipe:
            for session_id, _ in indexed:
                pipe.hgetall(_session_key(session_id))
            rows = await pipe.execute()
        stale = [session_id for (session_id, _), row in zip(indexed, rows) if not row]
        if stale:
            await client.zrem(index_key, *stale)
    except RedisError as error:
        raise SessionStoreUnavailable from error
    sessions = []
    for (_, last_active), row in zip(indexed, rows):
        if row:
            # آخرین فعالیت: امتیاز Sorted Set (touch_session) یا زمان ثبت‌شده در نوسازی، هرکدام تازه‌تر
            row["last_active_at"] = str(max(float(last_active), float(row.get("last_active_at") or 0)))
            sessions.append(row)
    return sessions


async def touch_session(session_id: str) -> bool:
    """
    روی هر درخواست احرازشده: آیا نشست هنوز معتبر است؟ (یک رفت‌وبرگشت Redis)
    آخرین فعالیت حداکثر هر ۶۰ ثانیه یک‌بار نوشته می‌شود (قفل SET NX)، نه در هر درخواست.
    """
    client = get_redis_client()
    key = _session_key(session_id)
    try:
        async with client.pipeline(transaction=False) as pipe:
            pipe.hget(key, "user_id")
            pipe.set(f"{SESSION_TOUCH_KEY_PREFIX}{session_id}", "1", nx=True, ex=ACTIVITY_THROTTLE_SECONDS)
            user_id, should_write = await pipe.execute()
        if user_id is None:
            return False
        if should_write:
            # فقط امتیاز Sorted Set (XX: ردیف نشستی را که هم‌زمان باطل شده دوباره نمی‌سازد). نوشتن در Hash
            # نشست ممکن بود نشستِ تازه حذف‌شده را بدون TTL دوباره بسازد.
            await client.zadd(_user_sessions_key(user_id), {session_id: time.time()}, xx=True)
    except RedisError as error:
        logger.error("بررسی نشست در Redis ناموفق بود: %s", error)
        raise SessionStoreUnavailable from error
    return True
