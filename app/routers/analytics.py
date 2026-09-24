"""
میکروسرویس داشبورد تحلیلی (Data Aggregation): API های تجمیعی آماده‌مصرف برای
نمودارسازهای فرانت‌اند، تا محاسبات سنگین (GROUP BY/COUNT/DATE_TRUNC) در
لایه‌ی بک‌اند و با کوئری‌های تجمیعی SQLAlchemy انجام شود، نه در فرانت‌اند:

- GET /api/v1/analytics/funnel                متریک‌های قیف استخدام (تعداد کارجویان در هر مرحله)
- GET /api/v1/analytics/applications-trend      سری زمانی روند ثبت درخواست‌ها (پیش‌فرض ۳۰ روز گذشته)

هر دو مسیر فقط برای Admin و HR_Manager («مدیر سازمان») در دسترس‌اند؛ طبق
معیار پذیرش تسک، سایر نقش‌ها (Candidate/Interviewer) با ۴۰۳ مواجه می‌شوند —
این محدودیت کاملاً روی dependencies=[Depends(require_roles(...))] پیاده شده،
نه با بررسی دستی داخل بدنه‌ی توابع (بنگرید app/core/deps.py::require_roles).

هر دو کوئری مستقیماً و بدون کش روی دیتابیس اجرا می‌شوند (بدون هیچ Snapshot یا
جدول گزارش‌گیری از پیش‌محاسبه‌شده) تا معیار پذیرش «بازتاب Real-time وضعیت
دیتابیس» تضمین شود.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.state_machine import FUNNEL_STAGES
from app.db.session import get_db
from app.models import Application, Job, StatusHistory
from app.schemas.analytics import (
    ApplicationsTrendResponse,
    DailyApplicationCount,
    FunnelStageCount,
    RecruitmentFunnelResponse,
)

router = APIRouter()

# «ادمین و مدیر سازمان» طبق معیار پذیرش تسک؛ همان دو نقشی که در
# app/routers/jobs.py (JOB_MANAGER_ROLES) و app/routers/applications.py
# به‌عنوان نقش‌های مدیریتی/HR تعریف شده‌اند.
ANALYTICS_ROLES = ("Admin", "HR_Manager")

_DEFAULT_TREND_DAYS = 30


async def _ensure_job_exists(db: AsyncSession, job_id: uuid.UUID) -> None:
    result = await db.execute(select(Job.id).where(Job.id == job_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="آگهی موردنظر یافت نشد.")


@router.get(
    "/funnel",
    response_model=RecruitmentFunnelResponse,
    status_code=status.HTTP_200_OK,
    tags=["Analytics"],
    summary="متریک‌های قیف استخدام (تعداد کارجویان در هر مرحله) — فقط Admin/HR_Manager",
    dependencies=[Depends(require_roles(*ANALYTICS_ROLES))],
)
async def get_recruitment_funnel(
    job_id: Optional[uuid.UUID] = Query(
        default=None,
        description="اختیاری — اگر ارسال شود، قیف فقط برای همین آگهی محاسبه می‌شود؛ در غیر این صورت قیف کل سازمان (همه‌ی آگهی‌ها).",
    ),
    db: AsyncSession = Depends(get_db),
) -> RecruitmentFunnelResponse:
    """
    خروجی، آرایه‌ای مرتب از {stage, count} به ترتیب واقعی مسیر قیف است
    (app/core/state_machine.py::FUNNEL_STAGES) — دقیقاً همان شکلی که
    کتابخانه‌های نمودارساز (Funnel/Bar Chart) بدون پردازش اضافه مصرف می‌کنند.

    ⚠️ تصمیم مهندسی مستند — معنای «count» یک شمارش تجمعی است، نه لحظه‌ای:
    برای هر مرحله، count یعنی «چند درخواست *تا این مرحله رسیده‌اند یا از آن
    گذشته‌اند*» (محاسبه‌شده از روی جدول status_history: هر درخواستی که
    حداقل یک بار new_status اش برابر آن مرحله بوده)، نه «چند درخواست همین
    الان دقیقاً روی این ستون از بورد کانبان نشسته‌اند». این تعریف، همان
    تعریف استاندارد «قیف» (Funnel) در تحلیل محصول است — عمداً به‌جای شمارش
    current_status انتخاب شد چون:
    ۱. اگر فقط current_status می‌شمردیم، کارجویانی که از یک مرحله جلوتر رفته‌اند
       دیگر در شمارش آن مرحله دیده نمی‌شدند و عدد مراحل اولیه به‌صورت مصنوعی
       کوچک می‌شد — قیف اصلاً شکل قیف (یکنواخت نزولی) پیدا نمی‌کرد و محاسبه‌ی
       نرخ ریزش بین مراحل (که هدف اصلی این تسک است) بی‌معنی می‌شد.
    ۲. چون ماشین وضعیت (app/core/state_machine.py) اجازه‌ی پرش از روی مراحل
       را نمی‌دهد، این تعریف تضمین می‌کند اعداد همیشه یکنواخت نزولی باشند
       (count هر مرحله <= مرحله‌ی قبلی‌اش) — دقیقاً شکلی که یک قیف واقعی باید
       داشته باشد.
    """
    if job_id is not None:
        await _ensure_job_exists(db, job_id)

    query = select(StatusHistory.new_status, func.count(func.distinct(StatusHistory.application_id))).where(
        StatusHistory.new_status.in_(FUNNEL_STAGES)
    )

    if job_id is not None:
        query = query.join(Application, Application.id == StatusHistory.application_id).where(
            Application.job_id == job_id
        )

    query = query.group_by(StatusHistory.new_status)

    result = await db.execute(query)
    counts_by_stage: dict[str, int] = dict(result.all())

    stages = [FunnelStageCount(stage=stage, count=counts_by_stage.get(stage, 0)) for stage in FUNNEL_STAGES]

    return RecruitmentFunnelResponse(job_id=job_id, stages=stages)


@router.get(
    "/applications-trend",
    response_model=ApplicationsTrendResponse,
    status_code=status.HTTP_200_OK,
    tags=["Analytics"],
    summary="سری زمانی روند ثبت درخواست‌های استخدام (پیش‌فرض ۳۰ روز گذشته) — فقط Admin/HR_Manager",
    dependencies=[Depends(require_roles(*ANALYTICS_ROLES))],
)
async def get_applications_trend(
    days: int = Query(
        default=_DEFAULT_TREND_DAYS,
        ge=1,
        le=365,
        description="اندازه‌ی بازه‌ی زمانی به روز (شامل امروز)؛ پیش‌فرض ۳۰ روز.",
    ),
    job_id: Optional[uuid.UUID] = Query(
        default=None,
        description="اختیاری — اگر ارسال شود، روند فقط برای همین آگهی محاسبه می‌شود.",
    ),
    db: AsyncSession = Depends(get_db),
) -> ApplicationsTrendResponse:
    """
    برای هر روز از بازه‌ی درخواستی، تعداد درخواست‌هایی که created_at شان در
    همان روز بوده برمی‌گرداند — بر اساس DATE_TRUNC('day', ...) پستگرس،
    گروه‌بندی‌شده و شمارش‌شده مستقیماً در دیتابیس (نه در پایتون/فرانت‌اند).

    ⚠️ تصمیم مهندسی مستند — Zero-Filling روزهای بدون داده: کوئری تجمعی SQL
    طبیعتاً فقط روزهایی را برمی‌گرداند که حداقل یک درخواست دارند؛ روزهای
    بدون هیچ درخواستی اصلاً ردیفی در نتیجه‌ی GROUP BY ندارند. چون معیار
    پذیرش تسک صراحتاً خروجی «کاملاً آماده برای مصرف در نمودارساز» می‌خواهد
    (بدون نیاز فرانت‌اند به پر کردن حفره‌های تاریخ)، بعد از گرفتن نتیجه از
    دیتابیس، بازه‌ی کامل `days` روزه در پایتون ساخته می‌شود و هر روز بدون
    داده با count=0 پر می‌شود — در غیر این صورت نمودار خط/میله‌ای فرانت‌اند
    برای روزهای بدون درخواست به‌جای افت به صفر، آن روز را کلاً حذف می‌کرد.
    """
    if job_id is not None:
        await _ensure_job_exists(db, job_id)

    today_utc = datetime.now(timezone.utc).date()
    start_date = today_utc - timedelta(days=days - 1)
    range_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)

    # date_trunc('day', ...) طبق Time Zone نشست دیتابیس گروه‌بندی می‌کند (که ممکن
    # است UTC نباشد)؛ چون بازه‌ی start_date/range_start بالا صراحتاً روی UTC
    # ساخته شده، برای اینکه مرز روزها همیشه دقیقاً با همان UTC هم‌راستا بماند
    # (فارغ از تنظیم Time Zone سرور پستگرس)، ابتدا created_at با
    # timezone('UTC', ...) به UTC قطعی تبدیل می‌شود و بعد truncate می‌گردد.
    day_bucket = func.date_trunc("day", func.timezone("UTC", Application.created_at)).label("day_bucket")
    query = (
        select(day_bucket, func.count().label("count"))
        .where(Application.created_at >= range_start)
        .group_by(day_bucket)
    )

    if job_id is not None:
        query = query.where(Application.job_id == job_id)

    result = await db.execute(query)
    counts_by_day: dict[date, int] = {row.day_bucket.date(): row.count for row in result.all()}

    series = [
        DailyApplicationCount(date=day, count=counts_by_day.get(day, 0))
        for day in (start_date + timedelta(days=offset) for offset in range(days))
    ]

    return ApplicationsTrendResponse(days=days, job_id=job_id, series=series)
