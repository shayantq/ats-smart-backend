"""
سیستم صف کارهای پس‌زمینه (Task Queue) با Redis Queue (RQ).

هدف: کارهای زمان‌بر و جانبی (مثل ارسال رزومه به موتور هوش مصنوعی یا ارسال
ایمیل انبوه) به‌جای اجرای مستقیم و مسدودکننده داخل درخواست HTTP، فقط به یک
صف در Redis اضافه می‌شوند. یک فرآیند Worker کاملاً جدا از سرور اصلی FastAPI
(دستور اجرا: `rq worker --url <REDIS_URL> default`) آن‌ها را در پس‌زمینه
پردازش می‌کند — کارکرد اصلی سرور هیچ‌وقت معطل این کارها نمی‌ماند.
"""

import logging
from typing import Any, Callable

from redis import Redis
from rq import Queue
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger("ats_smart.queue")

_redis_sync_client: Redis | None = None
_task_queue: Queue | None = None


def _get_sync_redis_client() -> Redis:
    """
    RQ خودش داخلی از کلاینت Redis همگام (sync) استفاده می‌کند، به همین دلیل
    این کلاینت از کلاینت Async مخصوص کش (app/core/redis_client.py) جداست.
    """
    global _redis_sync_client
    if _redis_sync_client is None:
        _redis_sync_client = Redis.from_url(settings.REDIS_URL)
    return _redis_sync_client


def get_task_queue() -> Queue:
    """صف پیش‌فرض کارهای پس‌زمینه («default») را برمی‌گرداند."""
    global _task_queue
    if _task_queue is None:
        _task_queue = Queue("default", connection=_get_sync_redis_client())
    return _task_queue


async def enqueue_task(func: Callable, *args: Any, **kwargs: Any) -> str | None:
    """
    یک کار (Task) را به‌صورت ناهمگام به صف Redis اضافه می‌کند.

    چون خودِ متد enqueue در RQ همگام (Sync) است، صدا زدنش داخل یک Thread Pool
    جداگانه (run_in_threadpool) انجام می‌شود تا Event Loop اصلی FastAPI هرگز
    معطل ارتباط شبکه‌ای با Redis نماند.

    اگر Redis در دسترس نبود، خطا فقط لاگ می‌شود و None برگردانده می‌شود —
    شکست یک کار جانبی/پس‌زمینه نباید کل درخواست اصلی کاربر را fail کند.
    """
    try:
        job = await run_in_threadpool(get_task_queue().enqueue, func, *args, **kwargs)
        logger.info("کار جدید با موفقیت به صف Redis اضافه شد: job_id=%s", job.id)
        return job.id
    except Exception as error:  # noqa: BLE001
        logger.error("افزودن کار به صف Redis ناموفق بود: %s", error)
        return None
