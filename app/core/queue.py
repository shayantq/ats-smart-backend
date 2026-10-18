"""
سیستم صف کارهای پس‌زمینه (Task Queue) با Redis Queue (RQ).

هدف: کارهای زمان‌بر و جانبی (مثل ارسال رزومه به موتور هوش مصنوعی یا ارسال
ایمیل انبوه) به‌جای اجرای مستقیم و مسدودکننده داخل درخواست HTTP، فقط به یک
صف در Redis اضافه می‌شوند. فرآیندهای Worker کاملاً جدا از سرور اصلی FastAPI
(python -m app.worker) آن‌ها را در پس‌زمینه پردازش می‌کنند — کارکرد اصلی سرور
هیچ‌وقت معطل این کارها نمی‌ماند.

چهار صف با اولویت و سیاست جدا (به‌جای یک صف مشترک):

    notifications  ایمیل‌های تراکنشی (OTP، تغییر وضعیت، پیشنهاد همکاری، یادآور مصاحبه) — فوری و سبک
    bulk           ایمیل‌های انبوه — کم‌اولویت؛ Worker همیشه اول notifications را خالی می‌کند،
                   پس هزاران ایمیل انبوه هرگز OTP یک کاربر را معطل نمی‌کنند
    resumes        پردازش سنگین رزومه (OCR ← NER ← موتور مهارت ← نمره‌ی تطابق) — Worker جدا
                   تا موجی از رزومه‌ها ایمیل‌ها را پشت سر خودش نگه ندارد
    default        بقیه‌ی کارها

هیچ کاری از دست نمی‌رود: همه‌ی کارها سیاست تلاش مجدد دارند (خطای گذرا، یا Worker ای که وسط کار
از بین رفته — RQ کار «رهاشده» را با همین سیاست دوباره در صف می‌گذارد)، کارهای ناموفق ۷ روز برای
بررسی نگه داشته می‌شوند و Redis با AOF و maxmemory-policy=noeviction هیچ کاری را بی‌صدا حذف نمی‌کند.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from redis import Redis
from rq import Queue, Retry
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger("ats_smart.queue")

QUEUE_NOTIFICATIONS = "notifications"
QUEUE_BULK = "bulk"
QUEUE_RESUMES = "resumes"
QUEUE_DEFAULT = "default"
# ترتیب اولویت یک Worker که به همه‌ی صف‌ها گوش می‌دهد (RQ همیشه از اولین صف غیرخالی برمی‌دارد)
ALL_QUEUES = (QUEUE_NOTIFICATIONS, QUEUE_RESUMES, QUEUE_BULK, QUEUE_DEFAULT)

# نتیجه‌ی کارهای موفق فقط ۱۰ دقیقه در Redis می‌ماند (حافظه‌ی Broker با حجم بالا رشد بی‌حد نمی‌کند)؛
# کارهای ناموفق ۷ روز برای بررسی و اجرای دوباره‌ی دستی
RESULT_TTL_SECONDS = 600
FAILURE_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class QueuePolicy:
    queue_name: str
    job_timeout: int
    retry: Retry


# کارهای ارسال ایمیل به یک سرویس بیرونی (SMTP) وابسته‌اند و خطاهای گذرا دارند — محدودیت نرخ ارسال،
# قطعی لحظه‌ای شبکه. یافته‌ی بازبینی Staging: چند ایمیل OTP با خطای «Too many emails per second»
# برای همیشه از دست رفتند. این کارها خودکار با فاصله‌ی ۳۰ ثانیه، ۲ دقیقه و ۱۰ دقیقه دوباره اجرا می‌شوند.
TRANSIENT_FAILURE_RETRY = Retry(max=3, interval=[30, 120, 600])

_NOTIFICATION_POLICY = QueuePolicy(QUEUE_NOTIFICATIONS, job_timeout=120, retry=TRANSIENT_FAILURE_RETRY)
_BULK_POLICY = QueuePolicy(QUEUE_BULK, job_timeout=120, retry=TRANSIENT_FAILURE_RETRY)
# OCR یک رزومه‌ی اسکن‌شده‌ی چندصفحه‌ای چند ده ثانیه CPU می‌گیرد؛ پردازه‌ی دوباره‌ی رزومه بی‌خطر است
# (نتیجه‌ی قبلی بازنویسی می‌شود)، پس Worker ازکارافتاده باعث گم شدن رزومه نمی‌شود
_RESUME_POLICY = QueuePolicy(QUEUE_RESUMES, job_timeout=300, retry=Retry(max=2, interval=[60, 300]))
_DEFAULT_POLICY = QueuePolicy(QUEUE_DEFAULT, job_timeout=180, retry=Retry(max=2, interval=[30, 120]))

_POLICY_BY_MODULE = {
    "app.tasks.notifications": _NOTIFICATION_POLICY,
    "app.tasks.resume_processing": _RESUME_POLICY,
}

# سقف هر Pipeline در enqueue_bulk — هزاران کار با چند رفت‌وبرگشت شبکه، نه هزاران
_BULK_CHUNK_SIZE = 500

_redis_sync_client: Redis | None = None
_task_queues: dict[str, Queue] = {}


def _get_sync_redis_client() -> Redis:
    """
    RQ خودش داخلی از کلاینت Redis همگام (sync) استفاده می‌کند، به همین دلیل
    این کلاینت از کلاینت Async مخصوص کش (app/core/redis_client.py) جداست.

    Timeout ها: Redis کند یا در دسترس نبودن آن هرگز Thread درخواست کاربر را بی‌انتها معطل نمی‌کند؛
    health_check_interval اتصال‌های مرده‌ی Pool (مثلاً بعد از ری‌استارت Redis) را پیش از استفاده جایگزین می‌کند.
    """
    global _redis_sync_client
    if _redis_sync_client is None:
        _redis_sync_client = Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
    return _redis_sync_client


def get_task_queue(name: str = QUEUE_DEFAULT) -> Queue:
    """صف کارهای پس‌زمینه با نام داده‌شده (پیش‌فرض «default») را برمی‌گرداند."""
    if name not in _task_queues:
        _task_queues[name] = Queue(name, connection=_get_sync_redis_client())
    return _task_queues[name]


def policy_for(func: Callable) -> QueuePolicy:
    """صف، سقف زمان اجرا و سیاست تلاش مجدد هر کار — بر اساس ماژول تابع آن."""
    return _POLICY_BY_MODULE.get(getattr(func, "__module__", ""), _DEFAULT_POLICY)


def _enqueue_options(func: Callable, kwargs: dict[str, Any]) -> tuple[Queue, dict[str, Any]]:
    policy = policy_for(func)
    queue_name = kwargs.pop("queue_name", policy.queue_name)
    kwargs.setdefault("retry", policy.retry)
    kwargs.setdefault("job_timeout", policy.job_timeout)
    kwargs.setdefault("result_ttl", RESULT_TTL_SECONDS)
    kwargs.setdefault("failure_ttl", FAILURE_TTL_SECONDS)
    return get_task_queue(queue_name), kwargs


async def enqueue_task(func: Callable, *args: Any, **kwargs: Any) -> str | None:
    """
    یک کار (Task) را به‌صورت ناهمگام به صف مناسبش در Redis اضافه می‌کند.

    چون خودِ متد enqueue در RQ همگام (Sync) است، صدا زدنش داخل یک Thread Pool
    جداگانه (run_in_threadpool) انجام می‌شود تا Event Loop اصلی FastAPI هرگز
    معطل ارتباط شبکه‌ای با Redis نماند.

    اگر Redis در دسترس نبود، خطا فقط لاگ می‌شود و None برگردانده می‌شود —
    شکست یک کار جانبی/پس‌زمینه نباید کل درخواست اصلی کاربر را fail کند.
    """
    try:
        task_queue, options = _enqueue_options(func, dict(kwargs))
        job = await run_in_threadpool(task_queue.enqueue, func, *args, **options)
        logger.info("کار جدید به صف «%s» اضافه شد: job_id=%s", task_queue.name, job.id)
        return job.id
    except Exception as error:  # noqa: BLE001
        logger.error("افزودن کار به صف Redis ناموفق بود: %s", error)
        return None


def _enqueue_bulk_sync(func: Callable, args_list: Sequence[tuple], queue_name: str) -> int:
    task_queue, options = _enqueue_options(func, {"queue_name": queue_name})
    # Queue.prepare_data همان job_timeout متد enqueue را با نام timeout می‌گیرد
    options["timeout"] = options.pop("job_timeout")
    total = 0
    for start in range(0, len(args_list), _BULK_CHUNK_SIZE):
        chunk = args_list[start : start + _BULK_CHUNK_SIZE]
        jobs_data = [Queue.prepare_data(func, args=tuple(args), **options) for args in chunk]
        total += len(task_queue.enqueue_many(jobs_data))
    return total


async def enqueue_bulk(func: Callable, args_list: Iterable[tuple], queue_name: str = QUEUE_BULK) -> int:
    """
    هزاران کار هم‌شکل (مثلاً ایمیل اطلاع‌رسانی به همه‌ی کارجویان یک آگهی) را یکجا به صف کم‌اولویت
    «bulk» اضافه می‌کند: هر ۵۰۰ کار با یک Pipeline (یک رفت‌وبرگشت شبکه)، نه یک درخواست به‌ازای هر کار.
    هر کار جداگانه اجرا و در صورت شکست جداگانه تکرار می‌شود (شکست یک ایمیل، بقیه را تکرار نمی‌کند).

    خروجی: تعداد کارهای اضافه‌شده (۰ در صورت در دسترس نبودن Redis — خطا لاگ می‌شود).
    """
    args_list = [tuple(args) for args in args_list]
    try:
        count = await run_in_threadpool(_enqueue_bulk_sync, func, args_list, queue_name)
        logger.info("%d کار انبوه به صف «%s» اضافه شد", count, queue_name)
        return count
    except Exception as error:  # noqa: BLE001
        logger.error("افزودن کارهای انبوه به صف Redis ناموفق بود: %s", error)
        return 0
