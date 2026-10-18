"""
اسکریپت اجرای Worker صف کارها (RQ) — سازگار با ویندوز.

مشکل: Worker پیش‌فرض RQ (چه از طریق CLI دستور `rq worker`) برای مدیریت
Timeout هر Job از ماژول signal پایتون و مشخصاً SIGALRM استفاده می‌کند —
که فقط روی لینوکس/مک وجود دارد و روی ویندوز باعث خطای
`AttributeError: module 'signal' has no attribute 'SIGALRM'` می‌شود.

راه‌حل: این اسکریپت به‌جای CLI پیش‌فرض، از TimerDeathPenalty (مبتنی بر
threading.Timer به‌جای سیگنال یونیکسی) استفاده می‌کند که روی هر سیستم‌عاملی
(از جمله ویندوز) به‌درستی کار می‌کند.

اجرا (به‌جای دستور `rq worker ...`):
    python -m app.worker                          همه‌ی صف‌ها به ترتیب اولویت (Docker Compose / توسعه)
    python -m app.worker notifications bulk default   فقط ایمیل‌ها و کارهای عمومی (Kubernetes: worker)
    python -m app.worker resumes                  فقط پردازش سنگین رزومه (Kubernetes: resume-worker)

ترتیب نام صف‌ها همان اولویت است: Worker همیشه اول از صف اول برمی‌دارد.
"""

import logging
import sys

from redis import Redis
from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty

from app.core.config import settings
from app.core.queue import ALL_QUEUES

logging.basicConfig(level=logging.INFO)


class WindowsCompatibleWorker(SimpleWorker):
    """همان SimpleWorker استاندارد RQ، فقط با یک death_penalty_class سازگار با ویندوز."""

    death_penalty_class = TimerDeathPenalty


def main(queue_names: list[str] | None = None) -> None:
    queue_names = queue_names or list(ALL_QUEUES)
    unknown = sorted(set(queue_names) - set(ALL_QUEUES))
    if unknown:
        sys.exit(f"صف ناشناخته: {', '.join(unknown)} — صف‌های مجاز: {', '.join(ALL_QUEUES)}")
    # health_check_interval: اتصال قطع‌شده (مثلاً بعد از ری‌استارت Redis) پیش از استفاده شناسایی می‌شود.
    # socket_timeout عمداً تنظیم نشده: Worker برای انتظار کار جدید از BLPOP چنددقیقه‌ای استفاده می‌کند.
    redis_connection = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=5, health_check_interval=30)
    worker = WindowsCompatibleWorker(queue_names, connection=redis_connection)
    logging.getLogger("ats_smart.worker").info("Worker صف‌ها (به ترتیب اولویت): %s", ", ".join(queue_names))
    # with_scheduler: تلاش مجدد کارهای ناموفق با فاصله‌ی زمانی (Retry در app/core/queue.py) — زمان‌بند
    # داخلی RQ پردازه‌ی جدا می‌سازد که روی ویندوز (توسعه‌ی محلی بدون Docker) پشتیبانی نمی‌شود
    worker.work(with_scheduler=sys.platform != "win32")


if __name__ == "__main__":
    main(sys.argv[1:])
