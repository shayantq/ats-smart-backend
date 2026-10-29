"""
«حق فراموش شدن» (GDPR، ماده‌ی ۱۷) — ناشناس‌سازی حساب کارجو به‌جای حذف فیزیکی (Hard Delete).

چرا حذف نه؟ ردیف‌های applications/status_history/interviews به کارجو ارجاع دارند و قیف استخدام، نرخ تبدیل و
روند درخواست‌های داشبورد HR (app/routers/analytics.py) از همین ردیف‌ها شمرده می‌شوند. حذف کارجو یا این ردیف‌ها
آمار گذشته‌ی سازمان را جابه‌جا می‌کرد. پس هویت پاک می‌شود و اعداد می‌مانند:

    پاک/تصادفی می‌شود                                   می‌ماند (بدون هویت)
    ───────────────────────────────────────────         ──────────────────────────────────────────
    نام، نام خانوادگی ← «کاربر حذف‌شده» + کد تصادفی      درخواست‌ها، وضعیت‌ها، تاریخچه‌ی وضعیت، تاریخ‌ها
    تلفن، آدرس، تگ‌های مهارت ← NULL                       نمره‌ی هوش مصنوعی هر درخواست
    ایمیل ← deleted-<تصادفی>@anonymized.invalid          تعداد مصاحبه‌ها و ارزیابی‌ها
    رمز ← تصادفی (غیرقابل ورود)، حساب غیرفعال            مهارت‌ها و سال‌های سابقه‌ی رزومه (عدد، بدون شرکت/تاریخ)
    فایل رزومه ← حذف از دیسک/S3، آدرسش هم پاک
    متن خام، داده‌ی استخراج‌شده، ایندکس جستجو ← NULL
    نشست‌ها، دستگاه‌های شناخته‌شده و کش‌های Redis

تراکنشی است: تغییرات دیتابیس یک‌جا commit می‌شوند؛ حذف فایل‌ها و پاک‌سازی Redis فقط بعد از commit موفق انجام
می‌شود (شکست آن‌ها لاگ می‌شود — بدون نام یا مسیر فایل — و ناشناس‌سازی دیتابیس را برنمی‌گرداند).
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cached
from app.core.redis_client import get_redis_client
from app.core.security import hash_password_async
from app.core.sessions import KNOWN_DEVICES_KEY_PREFIX, LOGIN_HISTORY_KEY_PREFIX, revoke_all_sessions
from app.core.storage import get_storage_backend
from app.core.tenancy import system_scope
from app.models import Candidate, Resume, User

logger = logging.getLogger("ats_smart.privacy")

# نسخه‌ی متن رضایت‌نامه‌ی حریم خصوصی فرم ثبت‌نام (frontend/src/pages/RegisterPage.tsx)؛ با تغییر متن، عوض شود
PRIVACY_NOTICE_VERSION = "2026-10"

ANONYMIZED_FIRST_NAME = "کاربر حذف‌شده"
ANONYMIZED_EMAIL_DOMAIN = "anonymized.invalid"
DELETED_FILE_URL_PREFIX = "deleted:"


@dataclass
class AnonymizationResult:
    resumes_cleared: int
    files_deleted: int


def _anonymous_skill_analysis(analysis: dict | None) -> dict | None:
    """فقط اعداد و مهارت‌های عمومی برای آمار؛ سوابق کاری (نام شرکت، عنوان شغلی، تاریخ‌ها) حذف می‌شوند."""
    if not analysis:
        return None
    return {"skills": analysis.get("skills") or [], "total_experience_years": analysis.get("total_experience_years")}


async def anonymize_candidate_account(db: AsyncSession, user: User) -> AnonymizationResult:
    # کار سطح پلتفرم روی داده‌ی خود کاربر (هویتش با توکن تأیید شده): رزومه‌ها و درخواست‌های کارجو در چند سازمان
    # پخش‌اند، پس پالیسی‌های RLS «یک سازمان» برای این عملیات صریحاً کنار گذاشته می‌شوند
    async with system_scope(db):
        candidate = (await db.execute(select(Candidate).where(Candidate.user_id == user.id))).scalar_one_or_none()
        file_urls: list[str] = []
        resumes: list[Resume] = []
        if candidate is not None:
            resumes = list((await db.execute(select(Resume).where(Resume.candidate_id == candidate.id))).scalars())
            for resume in resumes:
                if not resume.file_url.startswith(DELETED_FILE_URL_PREFIX):
                    file_urls.append(resume.file_url)
                resume.file_url = f"{DELETED_FILE_URL_PREFIX}{resume.id}"
                resume.raw_text = None  # ایندکس کور جستجو هم خودکار پاک می‌شود (listener مدل Resume)
                resume.parsed_data = None
                resume.skill_analysis = _anonymous_skill_analysis(resume.skill_analysis)
            candidate.first_name = ANONYMIZED_FIRST_NAME
            candidate.last_name = f"#{secrets.token_hex(3)}"
            candidate.phone = None
            candidate.location = None
            candidate.skills = None

        db_user = await db.get(User, user.id)
        db_user.email = f"deleted-{uuid.uuid4().hex}@{ANONYMIZED_EMAIL_DOMAIN}"
        db_user.password_hash = await hash_password_async(secrets.token_urlsafe(32))
        db_user.is_active = False
        db_user.anonymized_at = datetime.now(timezone.utc)
        await db.commit()

    files_deleted = 0
    storage = get_storage_backend()
    for file_url in file_urls:
        try:
            files_deleted += await storage.delete_file(file_url)
        except Exception as error:  # noqa: BLE001 - حذف فایل نباید ناشناس‌سازی دیتابیس را خنثی کند
            logger.error("حذف فایل رزومه‌ی حساب ناشناس‌شده ناموفق بود | user=%s | %s", user.id, type(error).__name__)

    try:
        await revoke_all_sessions(str(user.id))
        await get_redis_client().delete(f"{KNOWN_DEVICES_KEY_PREFIX}{user.id}", f"{LOGIN_HISTORY_KEY_PREFIX}{user.id}")
    except Exception as error:  # noqa: BLE001
        logger.error("پاک‌سازی نشست‌های حساب ناشناس‌شده ناموفق بود | user=%s | %s", user.id, type(error).__name__)
    await delete_cached(f"session:user:{user.id}")  # کش کاربر در get_current_user (ایمیل قبلی)

    logger.info("حساب کارجو ناشناس شد | user=%s | resumes=%d | files=%d", user.id, len(resumes), files_deleted)
    return AnonymizationResult(resumes_cleared=len(resumes), files_deleted=files_deleted)
