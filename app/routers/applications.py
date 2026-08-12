"""
میکروسرویس بورد کانبان فرآیند استخدام (Application Status Service):
- PUT /api/v1/applications/{id}/status/   جابه‌جایی وضعیت یک درخواست، طبق
  ماشین وضعیت صلب (Strict State Machine) تعریف‌شده در app/core/state_machine.py.

فقط نقش‌های Admin و HR_Manager اجازه‌ی جابه‌جایی وضعیت را دارند.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.state_machine import is_transition_allowed
from app.db.session import get_db
from app.models import Application, StatusHistory, User
from app.schemas.applications import ApplicationStatusUpdateRequest, ApplicationStatusUpdateResponse

router = APIRouter()

# طبق معیار پذیرش تسک، فقط مدیر سازمان (Admin) و کارشناس HR اجازه‌ی
# جابه‌جایی وضعیت درخواست‌ها روی بورد کانبان را دارند.
APPLICATION_MANAGER_ROLES = ("Admin", "HR_Manager")


@router.put(
    "/{application_id}/status",
    response_model=ApplicationStatusUpdateResponse,
    status_code=status.HTTP_200_OK,
    tags=["Applications"],
    summary="جابه‌جایی وضعیت یک درخواست روی بورد کانبان (ماشین وضعیت صلب)",
    dependencies=[Depends(require_roles(*APPLICATION_MANAGER_ROLES))],
)
async def update_application_status(
    application_id: uuid.UUID,
    payload: ApplicationStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationStatusUpdateResponse:
    """
    جابه‌جایی وضعیت یک درخواست، فقط اگر طبق قوانین ماشین وضعیت صلب مجاز باشد.

    ترتیب بررسی:
    ۱. اگر درخواست (Application) با این id وجود نداشته باشد -> 404.
    ۲. اگر current_status ارسالی توسط کلاینت با وضعیت واقعی رکورد در
       دیتابیس یکی نباشد (یعنی داده‌ی بورد کانبان کلاینت قدیمی/ناهماهنگ است)
       -> تراکنش Rollback و خطای 400 با پیام دقیق "Business Logic Violation".
    ۳. اگر current_status -> new_status طبق app/core/state_machine.py
       یک پرش غیرمجاز باشد (مثلاً Screening -> Hired) -> تراکنش Rollback
       و همان خطای 400 "Business Logic Violation".
    ۴. در غیر این صورت: current_status رکورد آپدیت می‌شود، updated_at
       به‌صورت خودکار توسط دیتابیس به‌روزرسانی می‌شود، و یک ردیف جدید
       در جدول StatusHistory با وضعیت قبلی/جدید و شناسه‌ی کاربر ثبت‌کننده
       درج می‌شود -> 200 OK.
    """
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()

    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="درخواست موردنظر یافت نشد.",
        )

    requested_current = payload.current_status.value
    requested_new = payload.new_status.value

    # قدم ۱: وضعیت فعلی ارسالی باید دقیقاً با وضعیت واقعی رکورد یکی باشد
    if application.current_status != requested_current:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business Logic Violation",
        )

    # قدم ۲: قانون ضدپرش (Anti-Skipping Rule) — هسته‌ی ماشین وضعیت صلب
    if not is_transition_allowed(requested_current, requested_new):
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business Logic Violation",
        )

    previous_status = application.current_status
    application.current_status = requested_new
    db.add(application)

    # ثبت لاگ تغییر وضعیت در StatusHistory بلافاصله پس از یک جابه‌جایی مجاز
    history_entry = StatusHistory(
        application_id=application.id,
        old_status=previous_status,
        new_status=requested_new,
        changed_by=current_user.id,
    )
    db.add(history_entry)

    await db.commit()
    await db.refresh(application)

    return ApplicationStatusUpdateResponse(
        application_id=application.id,
        previous_status=previous_status,
        new_status=application.current_status,
        updated_at=application.updated_at,
    )
