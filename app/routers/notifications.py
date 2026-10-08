"""
صندوق اعلان‌های داخل سایت (In-App Notifications) برای هر کاربر لاگین‌شده:
- GET /api/v1/notifications/me                لیست اعلان‌ها (جدیدترین اول) + تعداد خوانده‌نشده‌ها
- PUT /api/v1/notifications/{id}/read         علامت‌گذاری یک اعلان به‌عنوان خوانده‌شده
- PUT /api/v1/notifications/read-all          علامت‌گذاری همه‌ی اعلان‌ها به‌عنوان خوانده‌شده

فعلاً منبع اصلی این اعلان‌ها «کانال تیم فنی» است (هشدارهای مانیتورینگ و گزارش‌های
CI/CD — بنگرید app/routers/ops.py)، ولی مسیرها عمداً به نقش خاصی محدود نشده‌اند:
هر کاربر فقط و همیشه اعلان‌های خودش را می‌بیند (user_id از توکن، نه از ورودی).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.pagination import CursorParams, cursor_params, paginate_by_cursor
from app.db.session import get_db
from app.models import Notification, User
from app.schemas.notifications import MarkAllReadResponse, NotificationItem, NotificationListResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
    tags=["Notifications"],
    summary="لیست اعلان‌های کاربر لاگین‌شده (جدیدترین اول)",
)
async def list_my_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: CursorParams = Depends(cursor_params),
) -> NotificationListResponse:
    """
    صفحه‌بندی مبتنی بر نشانگر (created_at DESC) روی ایندکس مرکب
    (user_id, created_at, id) — بنگرید مایگریشن b5e2c9d4a710.
    """
    query = select(Notification).where(Notification.user_id == current_user.id)

    cursor_page = await paginate_by_cursor(
        db,
        query,
        sort_column=Notification.created_at,
        id_column=Notification.id,
        params=page,
        descending=True,
    )

    unread_count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        )
    ).scalar_one()

    return NotificationListResponse(
        items=[NotificationItem.model_validate(item) for item in cursor_page.items],
        unread_count=unread_count,
        next_cursor=cursor_page.next_cursor,
        previous_cursor=cursor_page.previous_cursor,
        has_next=cursor_page.has_next,
        has_previous=cursor_page.has_previous,
    )


@router.put(
    "/read-all",
    response_model=MarkAllReadResponse,
    status_code=status.HTTP_200_OK,
    tags=["Notifications"],
    summary="علامت‌گذاری همه‌ی اعلان‌های خوانده‌نشده به‌عنوان خوانده‌شده",
)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarkAllReadResponse:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    return MarkAllReadResponse(updated_count=result.rowcount or 0)


@router.put(
    "/{notification_id}/read",
    response_model=NotificationItem,
    status_code=status.HTTP_200_OK,
    tags=["Notifications"],
    summary="علامت‌گذاری یک اعلان به‌عنوان خوانده‌شده",
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationItem:
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="اعلان موردنظر یافت نشد.")

    notification.is_read = True
    await db.commit()
    await db.refresh(notification)
    return NotificationItem.model_validate(notification)
