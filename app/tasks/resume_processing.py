"""
کارهای پس‌زمینه‌ی مرتبط با پردازش رزومه.

این توابع توسط یک فرآیند Worker مجزا اجرا می‌شوند، نه توسط سرور اصلی FastAPI
(بنگرید app/worker.py برای اجرای سازگار با ویندوز، و README برای دستور اجرا).

دو خط لوله (settings.RESUME_PIPELINE):
    multi_agent (پیش‌فرض)  عامل ناظر + سه عامل تخصصی موازی (app/agents) ← JSON یکپارچه در resumes.agent_analysis
    linear                 خط لوله‌ی ترتیبی قبلی — برای بازگشت فوری، بدون تغییر کد یا صف
هر دو همان ورودی صف (شناسه‌ها/آدرس فایل)، همان صف و همان سیاست تلاش مجدد را دارند و skill_analysis/score_ai را
با همان شکل می‌نویسند (جستجو، آمار و UI بدون تغییر).
"""

import asyncio
import logging
import urllib.request
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.matching_engine import calculate_matching_score
from app.core.resume_parser import parse_resume_text
from app.core.skill_engine import run_skill_engine
from app.core.storage import resolve_local_media_path
from app.core.text_extraction import UnreadableResumeFileError, extract_raw_text
from app.db.session import worker_session_factory
from app.models import Application, Candidate, Job, Resume

logger = logging.getLogger("ats_smart.tasks.resume")

_FILE_DOWNLOAD_TIMEOUT_SECONDS = 30


def process_resume_task(application_id: str, file_url: str) -> None:
    """
    نقطه‌ی ورود Worker. تابع همگام (Sync) است چون RQ داخلی sync عمل می‌کند؛
    خودِ منطق اصلی async است (چون از همان AsyncSession مشترک پروژه استفاده
    می‌کند)، پس با asyncio.run() یک event loop مستقل برای اجرای این Job
    ساخته می‌شود — و اتصال دیتابیس هم مخصوص همین loop (بنگرید worker_session_factory).
    """
    asyncio.run(_run_job(application_id, file_url))


async def _run_job(application_id: str, file_url: str) -> None:
    async with worker_session_factory() as session_factory:
        await _process_resume_async(application_id, file_url, session_factory)


async def _process_resume_async(application_id: str, file_url: str, session_factory) -> None:
    if settings.RESUME_PIPELINE == "linear":
        await _process_resume_linear(application_id, file_url, session_factory)
    else:
        await _process_resume_multi_agent(application_id, file_url, session_factory)


async def _load_job_context(db, application_id: str, resume: Resume) -> dict | None:
    """ورودی نمره‌دهی عامل ناظر (فقط مقادیر ساده، تا Session دیتابیس در طول اجرای عامل‌ها باز نماند)."""
    application = (
        await db.execute(select(Application).where(Application.id == uuid.UUID(application_id)))
    ).scalar_one_or_none()
    if application is None:
        return None
    job = (await db.execute(select(Job).where(Job.id == application.job_id))).scalar_one_or_none()
    if job is None:
        return None
    candidate = (await db.execute(select(Candidate).where(Candidate.id == resume.candidate_id))).scalar_one_or_none()
    return {
        "title": job.title,
        "skills_required": job.skills_required,
        "required_seniority": job.required_seniority,
        "required_education": job.required_education,
        "location": job.location,
        "description": job.description,
        "candidate_location": candidate.location if candidate else None,
    }


async def _process_resume_multi_agent(application_id: str, file_url: str, session_factory) -> None:
    """
    اکوسیستم چندعاملی: فایل خام به عامل ناظر داده می‌شود؛ ناظر متن را یک‌بار استخراج و پارس می‌کند، سه عامل
    تخصصی (مهارت، اعتبارسنجی سوابق، مهارت نرم) را موازی اجرا و خروجی‌شان را جمع‌بندی می‌کند — بنگرید
    docs/agents/ARCHITECTURE.md. لاگ‌ها فقط شناسه و عدد دارند (بدون آدرس فایل یا متن رزومه).
    """
    # ایمپورت تنبل: LangGraph فقط در پردازه‌ی Worker بارگذاری شود، نه در API
    from app.agents.graph import run_agent_pipeline
    from app.agents.supervisor import to_skill_analysis

    async with session_factory() as db:
        resume = (await db.execute(select(Resume).where(Resume.file_url == file_url))).scalar_one_or_none()
        if resume is None:
            logger.error("رکورد رزومه متناظر با این file_url پیدا نشد | application_id=%s", application_id)
            return
        resume_id = resume.id
        job_context = await _load_job_context(db, application_id, resume)

    try:
        file_bytes = await asyncio.to_thread(_download_file, file_url)
    except Exception as error:  # noqa: BLE001
        logger.error(
            "دانلود فایل رزومه ناموفق بود | application_id=%s | resume_id=%s | error=%s",
            application_id,
            resume_id,
            type(error).__name__,
        )
        return

    try:
        result = await run_agent_pipeline(file_bytes, file_url, job_context)
    except UnreadableResumeFileError:
        logger.error(
            "استخراج متن رزومه ناموفق بود (فایل ناخوانا/خراب/قفل‌شده) | application_id=%s | resume_id=%s",
            application_id,
            resume_id,
        )
        return
    except Exception as error:  # noqa: BLE001 - هر خطای پیش‌بینی‌نشده فقط لاگ شود، نه کرش Worker
        logger.error(
            "خطای غیرمنتظره در اکوسیستم چندعاملی | application_id=%s | resume_id=%s | error=%s",
            application_id,
            resume_id,
            type(error).__name__,
        )
        return

    analysis = result.analysis
    async with session_factory() as db:
        resume = await db.get(Resume, resume_id)
        resume.raw_text = result.raw_text
        if result.parsed_data is not None:
            resume.parsed_data = result.parsed_data
        if analysis.skills.status == "completed" or analysis.experience.status == "completed":
            resume.skill_analysis = to_skill_analysis(analysis)
        resume.agent_analysis = analysis.model_dump(mode="json")
        if analysis.matching.score is not None:
            application = await db.get(Application, uuid.UUID(application_id))
            if application is not None:
                application.score_ai = round(analysis.matching.score)
        await db.commit()

    timings = analysis.timings_ms
    logger.info(
        "اکوسیستم چندعاملی رزومه را پردازش کرد | application_id=%s | resume_id=%s | وضعیت=%s | مهارت=%d | "
        "سابقه_سال=%s | هشدار=%d | تعارض=%d | نمره=%s | کل_ms=%s | عامل‌ها_ms=%s",
        application_id,
        resume_id,
        analysis.status,
        len(analysis.skills.items),
        analysis.experience.total_experience_years,
        len(analysis.flags),
        len(analysis.conflicts_resolved),
        analysis.matching.score,
        timings["total"].duration_ms,
        {name: timing.duration_ms for name, timing in timings.items() if name != "total"},
    )


async def _process_resume_linear(application_id: str, file_url: str, session_factory) -> None:
    """
    خط لوله‌ی ترتیبی قبلی (RESUME_PIPELINE=linear).

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
    logger.info("شروع پردازش پس‌زمینه‌ی رزومه (خطی) | application_id=%s", application_id)

    try:
        file_bytes = await asyncio.to_thread(_download_file, file_url)
    except Exception as error:
        logger.error(
            "دانلود فایل رزومه برای پردازش ناموفق بود | application_id=%s | error=%s",
            application_id,
            type(error).__name__,
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

    async with session_factory() as db:
        result = await db.execute(select(Resume).where(Resume.file_url == file_url))
        resume = result.scalar_one_or_none()

        if resume is None:
            logger.error("رکورد رزومه متناظر با این file_url پیدا نشد | application_id=%s", application_id)
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

                    candidate_result = await db.execute(select(Candidate).where(Candidate.id == resume.candidate_id))
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
                            candidate_total_experience_years=skill_analysis_dict.get("total_experience_years", 0.0),
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
            "موتور مهارت با موفقیت اجرا شد | application_id=%s | resume_id=%s | " "تعداد_مهارت=%d | سابقه_خالص_سال=%s",
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
    """
    محتوای فایل رزومه را برمی‌گرداند: در ذخیره‌سازی محلی مستقیم از دیسک مشترک
    (بدون وابستگی به بالا بودن سرور API — بنگرید resolve_local_media_path)، و در
    غیر این صورت (Object Storage) با دانلود HTTP از آدرس ذخیره‌شده‌اش.
    """
    local_path = resolve_local_media_path(file_url)
    if local_path is not None:
        return local_path.read_bytes()

    with urllib.request.urlopen(file_url, timeout=_FILE_DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read()
