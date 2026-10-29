"""
مسیرهای مخصوص داشبورد ادمین.
این روتر به‌عنوان نمونه‌ی عملی برای تست سیستم RBAC ساخته شده:
طبق مستند طراحی (بخش ۱۶.۵)، آمار کلان پلتفرم فقط باید در اختیار Admin باشد.

مدیریت نشست کارمندان سازمان (مقابله با ربوده شدن حساب): Admin نشست‌های فعال هر کارمند سازمان خودش را
می‌بیند و یکی یا همه را فوراً باطل می‌کند. کاربر سازمان دیگر (یا کارجو) → 404.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.sessions import SessionStoreUnavailable, list_sessions, revoke_all_sessions, revoke_session
from app.core.tenancy import current_tenant_id
from app.db.session import get_db
from app.models import Company, Job, User
from app.schemas.auth import SessionListResponse, SessionResponse

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
    # آمار سازمان خود ادمین: jobs/companies با فیلتر خودکار سازمان و RLS محدود می‌شوند؛ جدول users
    # سراسری است، پس شرطش صریح است (کارمندان همین سازمان)
    users_count = (
        await db.execute(select(func.count()).select_from(User).where(User.tenant_id == current_tenant_id()))
    ).scalar_one()
    companies_count = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
    jobs_count = (await db.execute(select(func.count()).select_from(Job))).scalar_one()

    return {
        "total_users": users_count,
        "total_companies": companies_count,
        "total_jobs": jobs_count,
    }


async def _tenant_member(db: AsyncSession, user_id: uuid.UUID) -> User:
    """جدول users سراسری است (RLS ندارد)؛ پس عضویت در سازمان Admin صریحاً شرط می‌شود."""
    member = (
        await db.execute(select(User).where(User.id == user_id, User.tenant_id == current_tenant_id()))
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="کاربر پیدا نشد.")
    return member


def _session_store_unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="سرویس نشست موقتاً در دسترس نیست.")


@router.get(
    "/users/{user_id}/sessions/",
    response_model=SessionListResponse,
    tags=["Admin"],
    summary="نشست‌های فعال یک کارمند سازمان (فقط Admin)",
    dependencies=[Depends(require_roles("Admin"))],
)
async def list_member_sessions(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> SessionListResponse:
    member = await _tenant_member(db, user_id)
    try:
        sessions = await list_sessions(str(member.id))
    except SessionStoreUnavailable:
        raise _session_store_unavailable()
    # Admin برای بررسی امنیتی IP کامل را می‌بیند
    return SessionListResponse(items=[SessionResponse.from_store(row, None, lambda ip: ip or "") for row in sessions])


@router.delete(
    "/users/{user_id}/sessions/{session_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin"],
    summary="ابطال فوری یک نشست کارمند سازمان (فقط Admin)",
    dependencies=[Depends(require_roles("Admin"))],
)
async def revoke_member_session(user_id: uuid.UUID, session_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    member = await _tenant_member(db, user_id)
    try:
        revoked = await revoke_session(session_id, user_id=str(member.id))
    except SessionStoreUnavailable:
        raise _session_store_unavailable()
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="نشست پیدا نشد.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/users/{user_id}/sessions/",
    tags=["Admin"],
    summary="خروج اجباری کارمند از همه‌ی دستگاه‌ها (فقط Admin)",
    dependencies=[Depends(require_roles("Admin"))],
)
async def revoke_all_member_sessions(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    member = await _tenant_member(db, user_id)
    try:
        revoked = await revoke_all_sessions(str(member.id))
    except SessionStoreUnavailable:
        raise _session_store_unavailable()
    return {"revoked": revoked}
