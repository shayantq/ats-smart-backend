"""
اسکیمای ورودی و خروجی مسیرهای پورتال اختصاصی کارجو (Candidate Dashboard):
- GET/PUT /api/v1/candidates/me                        پروفایل شخصی
- GET     /api/v1/candidates/me/applications             سیستم رهگیر وضعیت (Tracker)
- GET     /api/v1/candidates/me/offers                    صندوق ورودی پیشنهادهای شغلی
- PUT     /api/v1/candidates/me/applications/{id}/respond  پاسخ به یک پیشنهاد (قبول/رد)
"""

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import strip_html_tags


class CandidateProfileResponse(BaseModel):
    """پروفایل کامل کارجوی لاگین‌شده."""

    candidate_id: uuid.UUID = Field(validation_alias="id")
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    location: Optional[str] = None
    skills: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True, "populate_by_name": True}


class CandidateProfileUpdateRequest(BaseModel):
    """
    بدنه‌ی ویرایش پروفایل — هر فیلد اختیاری است (Partial Update)؛ فقط فیلدهایی
    که کارجو واقعاً ارسال کند تغییر می‌کنند، بقیه دست‌نخورده باقی می‌مانند.
    """

    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=20)
    location: Optional[str] = Field(default=None, max_length=100)
    skills: Optional[list[str]] = None

    @field_validator("first_name", "last_name", "phone", "location", mode="before")
    @classmethod
    def sanitize_text_fields(cls, value):
        """پاکسازی فیلدهای متنی آزاد از تگ HTML/جاوااسکریپت پیش از پردازش (دفاع XSS)."""
        if isinstance(value, str):
            return strip_html_tags(value)
        return value

    @field_validator("skills", mode="before")
    @classmethod
    def sanitize_skills(cls, value):
        if isinstance(value, list):
            return [strip_html_tags(v) if isinstance(v, str) else v for v in value]
        return value


class ApplicationTrackerItem(BaseModel):
    """یک ردیف از سیستم رهگیر وضعیت — نشان می‌دهد رزومه‌ی کارجو برای کدام آگهی، در کدام مرحله است."""

    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    current_status: str
    updated_at: datetime


class ApplicationTrackerResponse(BaseModel):
    total: int
    items: list[ApplicationTrackerItem]


class OfferInboxItem(BaseModel):
    """یک پیشنهاد همکاری فعال در صندوق ورودی کارجو (درخواستی که وضعیتش Offer است)."""

    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_name: Optional[str] = None
    updated_at: datetime


class OfferInboxResponse(BaseModel):
    total: int
    items: list[OfferInboxItem]


class OfferResponseRequest(BaseModel):
    """تصمیم کارجو درباره‌ی یک پیشنهاد شغلی."""

    decision: Literal["accept", "reject"]


class OfferResponseResult(BaseModel):
    application_id: uuid.UUID
    new_status: str
    message: str
