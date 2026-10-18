"""تست واحد محدودکننده‌ی نرخ (limiter.py): شمارنده‌ی مشترک بین همه‌ی نسخه‌های بک‌اند."""

from limits.storage import RedisStorage

from app.core.config import settings
from app.core.limiter import limiter


def test_rate_limit_counters_are_shared_in_redis_across_replicas():
    # با چند Pod پشت Load Balancer، شمارنده‌ی حافظه‌ای هر Pod جدا بود و سقف واقعی ۵ × تعداد Pod ها می‌شد
    assert isinstance(limiter._storage, RedisStorage)
    assert limiter._storage_uri == settings.REDIS_URL


def test_rate_limiter_falls_back_to_memory_when_redis_is_down():
    # قطعی Redis نباید مسیرهای ورود/ثبت‌نام را با خطای 500 از کار بیندازد
    assert limiter._in_memory_fallback_enabled is True
