"""
کارهای پس‌زمینه‌ی مرتبط با پردازش رزومه.

این توابع توسط یک فرآیند Worker مجزا اجرا می‌شوند، نه توسط سرور اصلی FastAPI
(بنگرید app/worker.py برای اجرای سازگار با ویندوز، و README برای دستور اجرا).
"""

import asyncio
import logging
import urllib.request

from sqlalchemy import select

from app.core.resume_parser import parse_resume_text
from app.core.skill_engine import run_skill_engine
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

    مرحله ۲: اجرای ماژول پارسینگ متنی و NER (app/core/resume_parser.py) روی
    همان متن خام، برای استخراج اطلاعات فردی، سوابق تحصیلی و تجربیات شغلی به
    شکل یک شیء JSON ساختاریافته که در ستون parsed_data همان ردیف ذخیره می‌شود.

    مرحله ۳: اجرای موتور مهارت (app/core/skill_engine.py) روی متن خام و
    تجربیات شغلی مرحله‌ی ۲ — تطبیق مهارت‌ها با گراف مهارت و محاسبه‌ی مجموع
    سال‌های سابقه‌ی کاری خالص (با کسر تداخل و فیلتر دوره‌های نامعتبر/بزرگ‌نمایی‌شده)
    که در ستون skill_analysis همان ردیف ذخیره می‌شود.

    در هر مرحله، اگر خطایی رخ دهد (دانلود ناموفق، فایل خراب/ناخوانا، یا هر
    خطای غیرمنتظره‌ی دیگر)، فرآیند برای همین رزومه متوقف می‌شود و خطا با
    جزئیات کافی لاگ می‌شود — بدون این‌که کل Worker (و پردازش سایر کارها) کرش کند.
    شکست یک مرحله باعث از دست رفتن نتیجه‌ی مراحل قبلی نمی‌شود؛ فقط همان ستون
    مرحله‌ی شکست‌خورده خالی می‌ماند.
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

    parsed_data_dict: dict | None = None
    try:
        parsed_data = parse_resume_text(raw_text)
        parsed_data_dict = parsed_data.model_dump()
    except Exception as error:  # noqa: BLE001 - شکست پارسینگ نباید کل Task را متوقف کند؛ raw_text باز هم ارزشمند است
        logger.error(
            "خطای غیرمنتظره هنگام پارس‌کردن ساختاریافته‌ی رزومه (NER) | application_id=%s | error=%s",
            application_id,
            error,
        )

    skill_analysis_dict: dict | None = None
    try:
        work_experience = parsed_data_dict.get("work_experience", []) if parsed_data_dict else []
        skill_analysis_dict = run_skill_engine(raw_text, work_experience)
    except Exception as error:  # noqa: BLE001 - شکست موتور مهارت نباید نتایج مراحل قبلی را از بین ببرد
        logger.error(
            "خطای غیرمنتظره هنگام اجرای موتور مهارت (Skill Engine) | application_id=%s | error=%s",
            application_id,
            error,
        )

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
        if parsed_data_dict is not None:
            resume.parsed_data = parsed_data_dict
        if skill_analysis_dict is not None:
            resume.skill_analysis = skill_analysis_dict
        db.add(resume)
        await db.commit()

    if parsed_data_dict is not None:
        logger.info(
            "متن خام و داده‌ی ساختاریافته‌ی رزومه با موفقیت ذخیره شدند | application_id=%s | resume_id=%s | "
            "تعداد_کاراکتر=%d | تعداد_تجربه=%d | تعداد_تحصیلات=%d",
            application_id,
            resume.id,
            len(raw_text),
            len(parsed_data_dict.get("work_experience", [])),
            len(parsed_data_dict.get("education", [])),
        )
    else:
        logger.info(
            "متن خام رزومه ذخیره شد، ولی پارسینگ ساختاریافته (NER) ناموفق بود | application_id=%s | resume_id=%s",
            application_id,
            resume.id,
        )

    if skill_analysis_dict is not None:
        logger.info(
            "موتور مهارت با موفقیت اجرا شد | application_id=%s | resume_id=%s | "
            "تعداد_مهارت=%d | سابقه_خالص_سال=%s",
            application_id,
            resume.id,
            len(skill_analysis_dict.get("skills", [])),
            skill_analysis_dict.get("total_experience_years"),
        )
    else:
        logger.info(
            "موتور مهارت اجرا نشد یا ناموفق بود | application_id=%s | resume_id=%s",
            application_id,
            resume.id,
        )


def _download_file(file_url: str) -> bytes:
    """فایل رزومه را از آدرس ذخیره‌شده‌اش (دیسک محلی از طریق HTTP یا Object Storage) دانلود می‌کند."""
    with urllib.request.urlopen(file_url, timeout=_FILE_DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read()
