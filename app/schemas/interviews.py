"""
اسکیمای ورودی و خروجی سرویس مدیریت مصاحبه‌ها (Interview Service):
- POST   /api/v1/interviews/            ساخت جلسه‌ی مصاحبه جدید
- GET    /api/v1/interviews/{id}          مشاهده‌ی جزئیات یک مصاحبه
- GET    /api/v1/interviews/?application_id=...   لیست مصاحبه‌های یک درخواست خاص
- PUT    /api/v1/interviews/{id}           ویرایش (تغییر زمان/مصاحبه‌کننده/لینک)
- DELETE /api/v1/interviews/{id}           لغو یک مصاحبه
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import strip_html_tags


class InterviewCreateRequest(BaseModel):
    """بدنه‌ی درخواست ساخت مصاحبه‌ی جدید."""

    application_id: uuid.UUID
    interviewer_id: uuid.UUID
    scheduled_at: datetime
    meeting_link: str = Field(min_length=1, max_length=500)

    @field_validator("meeting_link", mode="before")
    @classmethod
    def sanitize_meeting_link(cls, value: str) -> str:
        if isinstance(value, str):
            return strip_html_tags(value)
        return value

    @field_validator("scheduled_at")
    @classmethod
    def normalize_timezone(cls, value: datetime) -> datetime:
        """اگر کلاینت تاریخ را بدون Timezone بفرستد، به‌صورت UTC در نظر گرفته می‌شود."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class InterviewUpdateRequest(BaseModel):
    """بدنه‌ی ویرایش مصاحبه — هر فیلد اختیاری است (Partial Update)."""

    interviewer_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[datetime] = None
    meeting_link: Optional[str] = Field(default=None, min_length=1, max_length=500)

    @field_validator("meeting_link", mode="before")
    @classmethod
    def sanitize_meeting_link(cls, value):
        if isinstance(value, str):
            return strip_html_tags(value)
        return value

    @field_validator("scheduled_at")
    @classmethod
    def normalize_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class InterviewResponse(BaseModel):
    """ساختار خروجی یک مصاحبه."""

    interview_id: uuid.UUID
    application_id: uuid.UUID
    interviewer_id: uuid.UUID
    interviewer_name: str
    scheduled_at: Optional[datetime] = None
    meeting_link: Optional[str] = None


class InterviewListResponse(BaseModel):
    total: int
    items: list[InterviewResponse]
