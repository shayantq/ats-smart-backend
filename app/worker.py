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
    python -m app.worker
"""

import logging

from redis import Redis
from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty

from app.core.config import settings

logging.basicConfig(level=logging.INFO)


class WindowsCompatibleWorker(SimpleWorker):
    """همان SimpleWorker استاندارد RQ، فقط با یک death_penalty_class سازگار با ویندوز."""

    death_penalty_class = TimerDeathPenalty


def main() -> None:
    redis_connection = Redis.from_url(settings.REDIS_URL)
    worker = WindowsCompatibleWorker(["default"], connection=redis_connection)
    worker.work()


if __name__ == "__main__":
    main()
