"""
اسکیمای ورودی و خروجی مسیرهای مربوط به بورد کانبان درخواست‌های استخدام:
- GET /api/v1/applications/           لیست درخواست‌های یک آگهی خاص (برای رندر ستون‌ها/کارت‌ها)
- PUT /api/v1/applications/{id}/status   جابه‌جایی وضعیت یک درخواست
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.core.state_machine import ApplicationStatus


class ApplicationStatusUpdateRequest(BaseModel):
    """
    بدنه‌ی درخواست جابه‌جایی وضعیت.

    current_status و new_status هر دو الزامی‌اند و باید یکی از مقادیر
    مجاز ماشین وضعیت (app/core/state_machine.py) باشند؛ در غیر این صورت
    Pydantic خودش پیش از رسیدن به منطق تجاری، خطای 422 برمی‌گرداند.

    ارسال current_status توسط کلاینت عمداً الزامی شده تا سرور بتواند
    اطمینان حاصل کند وضعیت فعلی که فرانت‌اند می‌بیند، هم‌زمان با وضعیت
    واقعی رکورد در دیتابیس است (جلوگیری از رقابت/داده‌ی قدیمی روی بورد کانبان).
    """

    current_status: ApplicationStatus
    new_status: ApplicationStatus


class ApplicationStatusUpdateResponse(BaseModel):
    """ساختار پاسخ موفق (200) پس از یک جابه‌جایی مجاز وضعیت."""

    application_id: uuid.UUID
    previous_status: str
    new_status: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplicationListItem(BaseModel):
    """
    ساختار هر آیتم در لیست درخواست‌ها — دقیقاً همان داده‌ای که کارت کانبان
    در فرانت‌اند لازم دارد: نام کارجو و بالاترین امتیاز محاسبه‌شده‌ی هوش مصنوعی.
    """

    application_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    current_status: str
    score_ai: Optional[int] = None
    updated_at: datetime


class ApplicationListResponse(BaseModel):
    total: int
    items: list[ApplicationListItem]
