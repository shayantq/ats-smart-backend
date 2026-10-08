"""
اسکیمای مسیرهای صندوق اعلان‌های داخل سایت (In-App Notifications):
- GET /api/v1/notifications/me                لیست اعلان‌های کاربر لاگین‌شده
- PUT /api/v1/notifications/{id}/read         علامت‌گذاری یک اعلان به‌عنوان خوانده‌شده
- PUT /api/v1/notifications/read-all          علامت‌گذاری همه به‌عنوان خوانده‌شده
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: uuid.UUID
    title: str
    content: Optional[str] = None
    category: Optional[str] = None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """صفحه‌بندی مبتنی بر نشانگر (جدیدترین اول) + تعداد خوانده‌نشده‌ها برای نشان (Badge) در UI."""

    items: list[NotificationItem]
    unread_count: int
    next_cursor: Optional[str] = None
    previous_cursor: Optional[str] = None
    has_next: bool = False
    has_previous: bool = False


class MarkAllReadResponse(BaseModel):
    updated_count: int
