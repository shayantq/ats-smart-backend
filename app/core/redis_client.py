"""
اتصال به Redis — کلاینت ناهمگام (Async)، مخصوص لایه‌ی کش (app/core/cache.py).

اتصال صف کارهای پس‌زمینه (RQ) جدا و همگام (Sync) است، چون کتابخانه‌ی RQ خودش
داخلی از redis-py sync استفاده می‌کند؛ بنگرید app/core/queue.py.
"""

import logging

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger("ats_smart.redis")

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Singleton ساده: یک کلاینت Redis برای کل عمر پردازه‌ی سرور ساخته و مجدداً استفاده می‌شود."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def check_redis_connection() -> bool:
    """
    یک PING ساده به Redis می‌زند تا از برقراری موفق ارتباط مطمئن شود.
    در رویداد startup سرور (app/main.py) صدا زده می‌شود تا وضعیت اتصال واضح
    در لاگ سرور ثبت شود — بدون این‌که بالا آمدن خودِ سرور به آن وابسته باشد
    (اگر Redis موقتاً در دسترس نباشد، فقط قابلیت کش/صف غیرفعال می‌ماند، نه کل API).
    """
    try:
        await get_redis_client().ping()
        logger.info("اتصال به Redis با موفقیت برقرار شد.")
        return True
    except Exception as error:  # noqa: BLE001 - قطعی Redis نباید سرور را از کار بیندازد
        logger.error("اتصال به Redis برقرار نشد: %s", error)
        return False


async def close_redis_connection() -> None:
    """در رویداد shutdown سرور صدا زده می‌شود تا اتصال Redis تمیز بسته شود."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
