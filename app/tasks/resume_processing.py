"""
کارهای پس‌زمینه‌ی مرتبط با پردازش رزومه.

این توابع توسط یک فرآیند Worker مجزا اجرا می‌شوند، نه توسط سرور اصلی FastAPI
(بنگرید app/worker.py برای اجرای سازگار با ویندوز، و README برای دستور اجرا).
"""

import asyncio
import logging
import urllib.request

from sqlalchemy import select

from app.core.text_extraction import UnreadableResumeFileError, extract_raw_text
from app.db.session import AsyncSessionLocal
from app.models import Resume

logger = logging.getLogger("ats_smart.tasks.resume")

_FILE_DOWNLOAD_TIMEOUT_SECONDS = 30


def process_resume_task(application_id: str, file_url: str) -> None:
    """
    نقطه‌ی ورود Worker. تابع همگام (Sync) است چون RQ داخلی sync عمل می‌کند؛
    خودِ منطق اصلی async است (چون از همان AsyncSession مشترک پروژه استفاده
    می‌کند)، پس با asyncio.run() یک event loop مستقل برای اجرای این Job
    ساخته می‌شود.
    """
    asyncio.run(_process_resume_async(application_id, file_url))


async def _process_resume_async(application_id: str, file_url: str) -> None:
    """
    مرحله ۱ از خط لوله‌ی هوش مصنوعی: دانلود فایل رزومه از فضای ذخیره‌سازی،
    استخراج متن خام آن (مستقیم یا از طریق OCR — بنگرید app/core/text_extraction.py)،
    و ذخیره‌ی یکپارچه‌ی آن در ستون raw_text از جدول resumes.

    در هر مرحله، اگر خطایی رخ دهد (دانلود ناموفق، فایل خراب/ناخوانا، یا هر
    خطای غیرمنتظره‌ی دیگر)، فرآیند برای همین رزومه متوقف می‌شود و خطا با
    جزئیات کافی لاگ می‌شود — بدون این‌که کل Worker (و پردازش سایر کارها) کرش کند.
    """
    logger.info(
        "شروع پردازش پس‌زمینه‌ی رزومه | application_id=%s | file_url=%s",
        application_id,
        file_url,
    )

    try:
        file_bytes = await asyncio.to_thread(_download_file, file_url)
    except Exception as error:
        logger.error(
            "دانلود فایل رزومه برای پردازش ناموفق بود | application_id=%s | file_url=%s | error=%s",
            application_id,
            file_url,
            error,
        )
        return

    try:
        raw_text = extract_raw_text(file_bytes, filename=file_url)
    except UnreadableResumeFileError as error:
        logger.error(
            "استخراج متن رزومه ناموفق بود (فایل ناخوانا/خراب/قفل‌شده) | application_id=%s | error=%s",
            application_id,
            error,
        )
        return
    except Exception as error:  # noqa: BLE001 - هر خطای پیش‌بینی‌نشده هم باید فقط لاگ شود، نه کرش Worker
        logger.error(
            "خطای غیرمنتظره هنگام استخراج متن رزومه | application_id=%s | error=%s",
            application_id,
            error,
        )
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Resume).where(Resume.file_url == file_url))
        resume = result.scalar_one_or_none()

        if resume is None:
            logger.error(
                "رکورد رزومه متناظر با این file_url پیدا نشد | application_id=%s | file_url=%s",
                application_id,
                file_url,
            )
            return

        resume.raw_text = raw_text
        db.add(resume)
        await db.commit()

    logger.info(
        "متن خام رزومه با موفقیت استخراج و ذخیره شد | application_id=%s | resume_id=%s | تعداد_کاراکتر=%d",
        application_id,
        resume.id,
        len(raw_text),
    )


def _download_file(file_url: str) -> bytes:
    """فایل رزومه را از آدرس ذخیره‌شده‌اش (دیسک محلی از طریق HTTP یا Object Storage) دانلود می‌کند."""
    with urllib.request.urlopen(file_url, timeout=_FILE_DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read()
