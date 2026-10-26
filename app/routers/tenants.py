"""
مسیرهای سازمان جاری (Tenant) کاربر لاگین‌شده:

    GET  /api/v1/tenant         مشخصات سازمان (همه‌ی کارمندان سازمان)
    GET  /api/v1/tenant/users   فهرست کارمندان سازمان (فقط Admin)
    POST /api/v1/tenant/users   ساخت حساب HR_Manager یا Interviewer در همین سازمان (فقط Admin)

شناسه‌ی سازمان هیچ‌وقت از درخواست خوانده نمی‌شود؛ همیشه سازمان خودِ کاربر (Claim «tid» توکن،
تطبیق‌داده‌شده با دیتابیس در get_current_user) است — بنگرید app/core/tenancy.py.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.security import hash_password_async
from app.db.session import get_db
from app.models import Company, User
from app.schemas.tenants import StaffCreateRequest, StaffListResponse, StaffResponse, TenantResponse

router = APIRouter()

TENANT_MEMBER_ROLES = ("Admin", "HR_Manager", "Interviewer")


@router.get(
    "",
    response_model=TenantResponse,
    tags=["Tenant"],
    summary="مشخصات سازمان کاربر لاگین‌شده",
    dependencies=[Depends(require_roles(*TENANT_MEMBER_ROLES))],
)
async def get_my_tenant(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TenantResponse:
    company = (await db.execute(select(Company).where(Company.id == current_user.tenant_id))).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="سازمان یافت نشد.")
    return TenantResponse.model_validate(company)


@router.get(
    "/users",
    response_model=StaffListResponse,
    tags=["Tenant"],
    summary="فهرست کارمندان سازمان (فقط Admin)",
    dependencies=[Depends(require_roles("Admin"))],
)
async def list_tenant_staff(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> StaffListResponse:
    result = await db.execute(
        select(User).where(User.tenant_id == current_user.tenant_id).order_by(User.created_at, User.id)
    )
    return StaffListResponse(items=[StaffResponse.model_validate(user) for user in result.scalars()])


@router.post(
    "/users",
    response_model=StaffResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Tenant"],
    summary="ساخت حساب HR یا مصاحبه‌کننده در سازمان (فقط Admin)",
    dependencies=[Depends(require_roles("Admin"))],
)
async def create_tenant_staff(
    payload: StaffCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaffResponse:
    existing = (await db.execute(select(User.id).where(User.email == payload.email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="کاربری با این ایمیل قبلاً ثبت شده است.")

    staff = User(
        email=payload.email,
        password_hash=await hash_password_async(payload.password),
        role=payload.role.value,
        tenant_id=current_user.tenant_id,
    )
    db.add(staff)
    await db.commit()
    await db.refresh(staff)
    return StaffResponse.model_validate(staff)
