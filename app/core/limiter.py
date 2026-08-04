"""
پیکربندی محدودکننده‌ی نرخ درخواست‌ها (Rate Limiting).
کلید محدودیت، آی‌پی کاربر است؛ یعنی هر آی‌پی سقف مجاز خودش را دارد.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
