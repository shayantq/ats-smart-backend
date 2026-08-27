"""
تابع مشترک «یافتن یا ساخت پروفایل کارجو».

هم روتر آپلود رزومه (app/routers/resumes.py) و هم روتر پورتال کارجو
(app/routers/candidates.py) لازم دارند که پروفایل Candidate متناظر با
کاربر لاگین‌شده را داشته باشند؛ برای جلوگیری از تکرار کد، این تابع در
یک‌جا نگه‌داری می‌شود.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, User


async def get_or_create_candidate_profile(db: AsyncSession, user: User) -> Candidate:
    """
    چون هنوز فرآیند «تکمیل اجباری پروفایل بعد از ثبت‌نام» در پروژه پیاده‌سازی
    نشده، اولین باری که یک کاربر با نقش Candidate به هر مسیر مربوط به
    پروفایل/رزومه‌اش دسترسی پیدا می‌کند، یک پروفایل حداقلی برایش ساخته می‌شود
    (بعداً از طریق PUT /api/v1/candidates/me قابل تکمیل/ویرایش است).
    """
    result = await db.execute(select(Candidate).where(Candidate.user_id == user.id))
    candidate = result.scalar_one_or_none()
    if candidate is not None:
        return candidate

    placeholder_name = user.email.split("@")[0]
    candidate = Candidate(user_id=user.id, first_name=placeholder_name, last_name="")
    db.add(candidate)
    await db.flush()
    return candidate
