"""
زمان‌بند یادآور مصاحبه با rq-scheduler.

هدف: برخلاف صف معمولی RQ (که کارها فوری اجرا می‌شوند)، یادآور مصاحبه باید
دقیقاً در یک لحظه‌ی مشخص در آینده (۲۴ ساعت پیش از scheduled_at) اجرا شود —
نه فوری. rq-scheduler این قابلیت را روی همان Redis موجود پروژه اضافه می‌کند،
بدون نیاز به یک Cron/Polling جداگانه که هر چند دقیقه دیتابیس را چک کند.

⚠️ پیش‌نیاز اجرایی: علاوه بر Worker معمولی (app/worker.py)، یک فرآیند دیگر
هم باید در حال اجرا باشد تا کارهای زمان‌بندی‌شده در لحظه‌ی موعودشان واقعاً
وارد صف اصلی شوند: دستور `rqscheduler` (بخشی از پکیج rq-scheduler).
"""

import logging
from datetime import datetime, timedelta, timezone

from redis import Redis
from rq_scheduler import Scheduler

from app.core.config import settings
from app.tasks.notifications import send_interview_reminder_email_task

logger = logging.getLogger("ats_smart.interview_scheduler")

# طبق معیار پذیرش تسک: یادآور دقیقاً ۲۴ ساعت پیش از شروع جلسه ارسال می‌شود
REMINDER_LEAD_TIME = timedelta(hours=24)

_redis_connection: Redis | None = None
_scheduler: Scheduler | None = None


def _get_scheduler() -> Scheduler:
    global _redis_connection, _scheduler
    if _scheduler is None:
        _redis_connection = Redis.from_url(settings.REDIS_URL)
        _scheduler = Scheduler(queue_name="default", connection=_redis_connection)
    return _scheduler


def schedule_interview_reminder(
    *,
    interview_id: str,
    scheduled_at: datetime,
    candidate_email: str,
    candidate_name: str,
    interviewer_email: str,
    interviewer_name: str,
    meeting_link: str,
) -> list[str]:
    """
    یک یادآور برای هرکدام از دو نفر (کارجو و مصاحبه‌کننده) در ۲۴ ساعت پیش از
    scheduled_at زمان‌بندی می‌کند. اگر آن لحظه از قبل گذشته باشد (یعنی جلسه با
    فاصله‌ی کمتر از ۲۴ ساعت زمان‌بندی شده)، یادآور فوراً (نه در گذشته) اجرا
    می‌شود تا کارجو/مصاحبه‌کننده بی‌اطلاع نمانند.

    شناسه‌ی Job های زمان‌بندی‌شده برگردانده می‌شود تا در صورت تغییر زمان یا
    لغو مصاحبه، بتوان آن‌ها را cancel کرد (بنگرید cancel_interview_reminder).
    اگر ارتباط با Redis برقرار نشد، خطا فقط لاگ می‌شود و لیست خالی برمی‌گردد —
    شکست زمان‌بندی یادآور نباید خودِ ساخت/ویرایش مصاحبه را fail کند.
    """
    reminder_time = scheduled_at - REMINDER_LEAD_TIME
    now = datetime.now(timezone.utc)
    effective_time = reminder_time if reminder_time > now else now

    recipients = [
        (candidate_email, candidate_name),
        (interviewer_email, interviewer_name),
    ]

    job_ids: list[str] = []
    try:
        scheduler = _get_scheduler()
        for recipient_email, recipient_name in recipients:
            job = scheduler.enqueue_at(
                effective_time,
                send_interview_reminder_email_task,
                recipient_email,
                recipient_name,
                candidate_name,
                interviewer_name,
                scheduled_at.isoformat(),
                meeting_link,
            )
            job_ids.append(job.id)
    except Exception as error:  # noqa: BLE001
        logger.error("زمان‌بندی یادآور مصاحبه ناموفق بود | interview_id=%s | error=%s", interview_id, error)
        return []

    logger.info(
        "یادآور مصاحبه با موفقیت زمان‌بندی شد | interview_id=%s | زمان_اجرا=%s | job_ids=%s",
        interview_id,
        effective_time.isoformat(),
        job_ids,
    )
    return job_ids


def cancel_interview_reminder(job_ids: list[str] | None) -> None:
    """کارهای زمان‌بندی‌شده‌ی قبلی (در صورت تغییر زمان یا لغو مصاحبه) را از صف حذف می‌کند."""
    if not job_ids:
        return

    try:
        scheduler = _get_scheduler()
        for job_id in job_ids:
            scheduler.cancel(job_id)
    except Exception as error:  # noqa: BLE001
        logger.warning("لغو یادآورهای زمان‌بندی‌شده‌ی قبلی ناموفق بود | job_ids=%s | error=%s", job_ids, error)
