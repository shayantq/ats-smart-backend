"""
لایه‌ی سبک Cache روی Redis — برای داده‌هایی که مدام و پشت‌سرهم تکرار می‌شوند
(مثلاً نشست/جلسه‌ی کاربر لاگین‌شده که در هر درخواست محافظت‌شده دوباره خوانده
می‌شود؛ بنگرید استفاده‌اش در app/core/deps.py).

طراحی عمدی: اگر Redis موقتاً در دسترس نباشد، هر تابع این ماژول فقط خطا را
لاگ می‌کند و None/عدم-انجام برمی‌گرداند — کش یک بهینه‌سازی سرعت است، نه یک
وابستگی حیاتی؛ نبودش هرگز نباید کل API را از کار بیندازد (کد بالادستی همیشه
باید بتواند در نبود کش، مستقیم از دیتابیس بخواند).
"""

import json
import logging
from typing import Any

from app.core.redis_client import get_redis_client

logger = logging.getLogger("ats_smart.cache")


async def get_cached_json(key: str) -> Any | None:
    """مقدار کش‌شده را با کلید مشخص برمی‌گرداند؛ اگر وجود نداشت یا خطا داد -> None."""
    try:
        raw_value = await get_redis_client().get(key)
    except Exception as error:  # noqa: BLE001
        logger.warning("خواندن کش برای کلید %s ناموفق بود: %s", key, error)
        return None

    if raw_value is None:
        return None

    try:
        return json.loads(raw_value)
    except (TypeError, ValueError):
        return None


async def set_cached_json(key: str, value: Any, ttl_seconds: int) -> None:
    """مقدار را به‌صورت JSON در Redis ذخیره می‌کند با یک زمان انقضای مشخص (TTL)."""
    try:
        await get_redis_client().set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as error:  # noqa: BLE001
        logger.warning("نوشتن کش برای کلید %s ناموفق بود: %s", key, error)


async def delete_cached(key: str) -> None:
    """یک کلید مشخص را از کش حذف می‌کند (مثلاً هنگام خروج کاربر یا تغییر نقش او)."""
    try:
        await get_redis_client().delete(key)
    except Exception as error:  # noqa: BLE001
        logger.warning("حذف کش برای کلید %s ناموفق بود: %s", key, error)
