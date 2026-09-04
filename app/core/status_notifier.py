"""
متد متصل‌کننده (Hook) بین ماشین وضعیت صلب (app/core/state_machine.py) و
زیرسیستم اطلاع‌رسانی. بعد از هر تغییر وضعیت موفق یک درخواست — چه از بورد
کانبان HR (app/routers/applications.py)، چه از پاسخ کارجو به یک پیشنهاد
(app/routers/candidates.py) — trigger_status_change_email باید صدا زده شود
تا در صورت لزوم، ایمیل متناظر همان وضعیت جدید به صف Redis اضافه شود.

طراحی عمدی: این تابع همیشه باید با asyncio.create_task فراخوانی شود
(fire-and-forget)، نه await مستقیم داخل یک درخواست HTTP — دقیقاً طبق همان
الگوی app/routers/resumes.py. به همین دلیل، Session دیتابیس مستقل خودش را
باز می‌کند (نه Session مربوط به همان درخواست HTTP)، چون آن Session ممکن است
پیش از پایان واقعی این تابع پس‌زمینه، توسط FastAPI بسته شده باشد.
"""

import logging
import uuid

from sqlalchemy import select

from app.core.queue import enqueue_task
from app.db.session import AsyncSessionLocal
from app.models import Candidate, Company, Job, User
from app.tasks.notifications import (
    STATUS_NOTIFICATION_STAGES,
    send_job_offer_email_task,
    send_status_update_email_task,
)

logger = logging.getLogger("ats_smart.status_notifier")

# وضعیت‌هایی که برایشان ایمیل تعریف شده: Offer (قالب اختصاصی) + هرچه در
# STATUS_NOTIFICATION_STAGES باشد (Screening, Technical Interview, ...)
_NOTIFIABLE_STATUSES = {"Offer", *STATUS_NOTIFICATION_STAGES.keys()}


async def trigger_status_change_email(*, candidate_id: uuid.UUID, job_id: uuid.UUID, new_status: str) -> None:
    """
    اگر new_status نیاز به اطلاع‌رسانی ایمیلی داشته باشد، اطلاعات لازم (ایمیل و
    نام کارجو + عنوان آگهی + نام شرکت در صورت وجود) از دیتابیس خوانده می‌شود
    و Task ایمیل مناسب به صف اضافه می‌گردد. برای وضعیت‌هایی که ایمیلی برایشان
    تعریف نشده (مثلاً Draft یا Applied)، این تابع بی‌سروصدا و فوری برمی‌گردد.
    """
    if new_status not in _NOTIFIABLE_STATUSES:
        return

    async with AsyncSessionLocal() as db:
        candidate_result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
        candidate = candidate_result.scalar_one_or_none()
        if candidate is None:
            logger.error("هوک اطلاع‌رسانی: پروفایل کارجو پیدا نشد | candidate_id=%s", candidate_id)
            return

        user_result = await db.execute(select(User).where(User.id == candidate.user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.error("هوک اطلاع‌رسانی: کاربر متناظر کارجو پیدا نشد | candidate_id=%s", candidate_id)
            return

        job_result = await db.execute(select(Job).where(Job.id == job_id))
        job = job_result.scalar_one_or_none()
        if job is None:
            logger.error("هوک اطلاع‌رسانی: آگهی شغلی پیدا نشد | job_id=%s", job_id)
            return

        candidate_name = f"{candidate.first_name} {candidate.last_name}".strip() or user.email

        if new_status == "Offer":
            company_name: str | None = None
            if job.company_id is not None:
                company_result = await db.execute(select(Company).where(Company.id == job.company_id))
                company = company_result.scalar_one_or_none()
                company_name = company.name if company else None

            await enqueue_task(send_job_offer_email_task, user.email, candidate_name, job.title, company_name)
        else:
            await enqueue_task(send_status_update_email_task, user.email, candidate_name, job.title, new_status)
