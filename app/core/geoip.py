"""
موقعیت جغرافیایی تقریبی IP (کشور، شهر، مختصات) برای تشخیص ورود مشکوک — app/core/sessions.py.

منبع: یک فایل mmdb محلی (DB-IP City Lite، رایگان و بدون کلید، مجوز CC BY 4.0 — https://db-ip.com؛
deploy/geoip-update.sh ماهانه دانلودش می‌کند).
فایل با mmap باز می‌شود: سیستم‌عامل فقط صفحه‌هایی از فایل را که واقعاً خوانده می‌شوند در حافظه نگه می‌دارد،
نه کل ~۱۲۰ مگابایت را. هیچ درخواست شبکه‌ای به سرویس بیرونی فرستاده نمی‌شود (IP کاربران جایی نمی‌رود).

نبودِ فایل، IP خصوصی/محلی یا هر خطای خواندن → None؛ بررسی جغرافیایی رد می‌شود ولی ورود هرگز شکست نمی‌خورد.
"""

import ipaddress
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

import maxminddb

from app.core.config import settings

logger = logging.getLogger("ats_smart.geoip")

EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class GeoLocation:
    country_code: str | None
    country: str | None
    city: str | None
    latitude: float | None
    longitude: float | None

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def label(self) -> str:
        return "، ".join(part for part in (self.city, self.country) if part) or "نامشخص"


# دیتابیس بعد از استقرار در پس‌زمینه دانلود می‌شود (deploy/geoip-update.sh)؛ نبودنش فقط تا این مدت
# به خاطر سپرده می‌شود و بعد دوباره امتحان می‌شود — بدون نیاز به ری‌استارت API
_RETRY_MISSING_SECONDS = 600
_state: dict = {"reader": None, "checked_at": None}


def _open_reader() -> maxminddb.Reader | None:
    path = settings.GEOIP_DB_PATH
    if not path or not Path(path).is_file():
        logger.info("دیتابیس GeoIP تنظیم یا پیدا نشد (%s) — بررسی جغرافیایی ورود غیرفعال است", path or "-")
        return None
    try:
        return maxminddb.open_database(path, maxminddb.MODE_MMAP)
    except Exception as error:  # noqa: BLE001 - فایل خراب نباید ورود را از کار بیندازد
        logger.error("باز کردن دیتابیس GeoIP ناموفق بود: %s", error)
        return None


def _reader() -> maxminddb.Reader | None:
    if _state["reader"] is None:
        now = time.monotonic()
        if _state["checked_at"] is None or now - _state["checked_at"] >= _RETRY_MISSING_SECONDS:
            _state["checked_at"] = now
            _state["reader"] = _open_reader()
    return _state["reader"]


def reset_reader_cache() -> None:
    _state.update(reader=None, checked_at=None)


def is_public_ip(ip: str | None) -> bool:
    try:
        return bool(ip) and ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def lookup(ip: str | None) -> GeoLocation | None:
    if not is_public_ip(ip):
        return None
    reader = _reader()
    if reader is None:
        return None
    try:
        record = reader.get(ip)
    except Exception as error:  # noqa: BLE001
        logger.warning("جستجوی GeoIP برای %s ناموفق بود: %s", ip, error)
        return None
    if not record:
        return None
    country = record.get("country") or {}
    location = record.get("location") or {}
    return GeoLocation(
        country_code=country.get("iso_code"),
        country=(country.get("names") or {}).get("en"),
        city=((record.get("city") or {}).get("names") or {}).get("en"),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """فاصله‌ی دایره‌ی عظیمه بین دو نقطه روی کره‌ی زمین (کیلومتر)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
