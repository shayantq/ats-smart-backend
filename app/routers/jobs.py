"""
میکروسرویس مدیریت مشاغل (Job Service):
- POST   /api/v1/jobs/       ساخت آگهی جدید (فقط مدیر سازمان / HR)
- GET    /api/v1/jobs/       دریافت لیست آگهی‌ها (عمومی)
- DELETE /api/v1/jobs/{id}/  بستن آگهی (Soft Delete) (فقط مدیر سازمان / HR)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Job, User
from app.schemas.jobs import JobCreateRequest, JobListResponse, JobResponse

router = APIRouter()

# طبق مستند طراحی، ساخت/بستن آگهی فقط برای مدیر سازمان (Admin) و کارشناس HR مجاز است
JOB_MANAGER_ROLES = ("Admin", "HR_Manager")


@router.post(
    "/",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Jobs"],
    summary="ساخت و انتشار آگهی شغلی جدید",
    dependencies=[Depends(require_roles(*JOB_MANAGER_ROLES))],
)
async def create_job(
    payload: JobCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """
    آگهی جدید را با وضعیت اولیه‌ی "Active" می‌سازد.
    دسترسی این مسیر با dependencies=[Depends(require_roles(...))] محدود شده:
    بدون توکن -> 401 ، با نقش غیرمجاز (مثلاً Candidate) -> 403.
    """
    new_job = Job(
        title=payload.title,
        department=payload.department,
        description=payload.description,
        skills_required=payload.skills_required,
        salary_range=payload.salary_range,
        status="Active",
        created_by=current_user.id,
    )

    db.add(new_job)
    await db.commit()
    await db.refresh(new_job)

    return JobResponse.model_validate(new_job)


@router.get(
    "/",
    response_model=JobListResponse,
    status_code=status.HTTP_200_OK,
    tags=["Jobs"],
    summary="دریافت لیست آگهی‌های شغلی (عمومی)",
)
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status", description="فیلتر بر اساس وضعیت آگهی"),
    department: str | None = Query(default=None, description="فیلتر بر اساس دپارتمان"),
) -> JobListResponse:
    """
    این مسیر عمومی است (بدون نیاز به توکن) تا کارجویان هم بتوانند آگهی‌ها را ببینند.
    فیلترهای اولیه: status و department (هر دو اختیاری).
    """
    query = select(Job)

    if status_filter is not None:
        query = query.where(Job.status == status_filter)
    if department is not None:
        query = query.where(Job.department == department)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return JobListResponse(
        total=len(jobs),
        items=[JobResponse.model_validate(job) for job in jobs],
    )


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_200_OK,
    tags=["Jobs"],
    summary="بستن (حذف منطقی) یک آگهی شغلی",
    dependencies=[Depends(require_roles(*JOB_MANAGER_ROLES))],
)
async def close_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """
    حذف منطقی (Soft Delete): رکورد از دیتابیس پاک نمی‌شود، فقط status به "Closed" تغییر می‌کند
    تا تاریخچه‌ی آگهی (مثلاً برای گزارش‌گیری‌های آینده) از بین نرود.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="آگهی موردنظر یافت نشد.")

    job.status = "Closed"
    await db.commit()

    return {"job_id": job.id, "status": job.status, "message": "آگهی با موفقیت بسته شد."}
