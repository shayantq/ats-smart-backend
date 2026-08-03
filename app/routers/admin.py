"""
مسیرهای مخصوص داشبورد ادمین.
این روتر به‌عنوان نمونه‌ی عملی برای تست سیستم RBAC ساخته شده:
طبق مستند طراحی (بخش ۱۶.۵)، آمار کلان پلتفرم فقط باید در اختیار Admin باشد.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.db.session import get_db
from app.models import Company, Job, User

router = APIRouter()


@router.get(
    "/stats",
    tags=["Admin"],
    summary="آمار کلان پلتفرم (فقط برای نقش Admin)",
    dependencies=[Depends(require_roles("Admin"))],
)
async def get_admin_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """
    یک نمونه‌ی واقعی از داده‌ی حساس مدیریتی که طبق مستند فقط ادمین باید ببیندش.
    محافظت این مسیر کاملاً روی dependencies=[Depends(require_roles("Admin"))]
    در دکوراتور بالا انجام شده، نه داخل بدنه‌ی تابع.
    """
    users_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    companies_count = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
    jobs_count = (await db.execute(select(func.count()).select_from(Job))).scalar_one()

    return {
        "total_users": users_count,
        "total_companies": companies_count,
        "total_jobs": jobs_count,
    }
