"""
پیکربندی محدودکننده‌ی نرخ درخواست‌ها (Rate Limiting).
کلید محدودیت، آی‌پی کاربر است؛ یعنی هر آی‌پی سقف مجاز خودش را دارد.

شمارنده‌ها در Redis مشترک نگه داشته می‌شوند، نه در حافظه‌ی هر پردازه: با چند نسخه‌ی بک‌اند پشت
Load Balancer (مقیاس افقی / HPA)، شمارنده‌ی حافظه‌ای هر نسخه جدا بود و سقف واقعی «۵ × تعداد نسخه‌ها»
می‌شد. اگر Redis در دسترس نباشد، موقتاً به شمارنده‌ی حافظه‌ای برمی‌گردد (درخواست‌ها با خطا رد نمی‌شوند).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
    key_prefix="ratelimit",
)
