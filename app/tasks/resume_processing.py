"""
کارهای پس‌زمینه‌ی مرتبط با پردازش رزومه.

این توابع توسط یک فرآیند Worker مجزا اجرا می‌شوند، نه توسط سرور اصلی FastAPI
(بنگرید app/worker.py برای اجرای سازگار با ویندوز، و README برای دستور اجرا).
"""

import asyncio
import logging
import urllib.request
import uuid

from sqlalchemy import select

from app.core.matching_engine import calculate_matching_score
from app.core.resume_parser import parse_resume_text
from app.core.skill_engine import run_skill_engine
from app.core.text_extraction import UnreadableResumeFileError, extract_raw_text
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Job, Resume

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
    مرحله ۱: دانلود فایل رزومه از فضای ذخیره‌سازی، استخراج متن خام آن (مستقیم
    یا از طریق OCR — بنگرید app/core/text_extraction.py)، و ذخیره در raw_text.

    مرحله ۲: پارسینگ متنی و NER (app/core/resume_parser.py) — اطلاعات فردی،
    سوابق تحصیلی و تجربیات شغلی، ذخیره در ستون parsed_data.

    مرحله ۳: موتور مهارت (app/core/skill_engine.py) — تطبیق مهارت‌ها با گراف
    مهارت + محاسبه‌ی سابقه‌ی کاری خالص، ذخیره در ستون skill_analysis.

    مرحله ۴ (نهایی): موتور نمره‌دهی و رتبه‌بندی (app/core/matching_engine.py) —
    رزومه‌ی ساختاریافته (خروجی مراحل ۲ و ۳) در برابر نیازمندی‌های همان آگهی
    شغلی که این Application برایش ثبت شده قرار می‌گیرد و نمره‌ی نهایی (۰ تا ۱۰۰)
    در ستون score_ai جدول applications ذخیره می‌شود.

    در هر مرحله، اگر خطایی رخ دهد، فرآیند برای همین رزومه متوقف می‌شود و خطا
    با جزئیات کافی لاگ می‌شود — بدون این‌که کل Worker (و پردازش سایر کارها)
    کرش کند. شکست یک مرحله باعث از دست رفتن نتیجه‌ی مراحل قبلی نمی‌شود.
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

        # مرحله ۴: نمره‌دهی و رتبه‌بندی — فقط اگر مراحل NER و Skill Engine هر دو
        # موفق بوده باشند (بدون داده‌ی ساختاریافته، نمره‌دهی بی‌معنی است)
        matching_score_dict: dict | None = None
        if parsed_data_dict is not None and skill_analysis_dict is not None:
            try:
                application_result = await db.execute(
                    select(Application).where(Application.id == uuid.UUID(application_id))
                )
                application = application_result.scalar_one_or_none()

                if application is None:
                    logger.error("رکورد Application پیدا نشد | application_id=%s", application_id)
                else:
                    job_result = await db.execute(select(Job).where(Job.id == application.job_id))
                    job = job_result.scalar_one_or_none()

                    candidate_result = await db.execute(
                        select(Candidate).where(Candidate.id == resume.candidate_id)
                    )
                    candidate = candidate_result.scalar_one_or_none()

                    if job is None:
                        logger.error(
                            "آگهی شغلی مرتبط با این درخواست پیدا نشد | application_id=%s | job_id=%s",
                            application_id,
                            application.job_id,
                        )
                    else:
                        candidate_job_titles = [
                            entry.get("job_title")
                            for entry in parsed_data_dict.get("work_experience", [])
                            if entry.get("job_title")
                        ]

                        matching_score_dict = calculate_matching_score(
                            job_skills_required=job.skills_required,
                            job_title=job.title,
                            job_required_seniority=job.required_seniority,
                            job_required_education=job.required_education,
                            job_location=job.location,
                            job_description=job.description,
                            candidate_skills=skill_analysis_dict.get("skills", []),
                            candidate_job_titles=candidate_job_titles,
                            candidate_total_experience_years=skill_analysis_dict.get(
                                "total_experience_years", 0.0
                            ),
                            candidate_education_entries=parsed_data_dict.get("education", []),
                            candidate_location=candidate.location if candidate else None,
                        )
                        application.score_ai = round(matching_score_dict["final_score"])
                        db.add(application)
            except Exception as error:  # noqa: BLE001 - شکست نمره‌دهی نباید نتایج مراحل قبلی را از بین ببرد
                logger.error(
                    "خطای غیرمنتظره هنگام محاسبه‌ی نمره‌ی تطابق (Matching Score) | application_id=%s | error=%s",
                    application_id,
                    error,
                )

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

    if matching_score_dict is not None:
        logger.info(
            "نمره‌ی تطابق (Matching Score) با موفقیت محاسبه و ذخیره شد | application_id=%s | "
            "نمره_نهایی=%s | ریزنمرات=%s",
            application_id,
            matching_score_dict["final_score"],
            matching_score_dict["breakdown"],
        )
    else:
        logger.info(
            "نمره‌ی تطابق محاسبه نشد یا ناموفق بود | application_id=%s",
            application_id,
        )


def _download_file(file_url: str) -> bytes:
    """فایل رزومه را از آدرس ذخیره‌شده‌اش (دیسک محلی از طریق HTTP یا Object Storage) دانلود می‌کند."""
    with urllib.request.urlopen(file_url, timeout=_FILE_DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read()
