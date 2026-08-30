"""
اسکیمای ورودی و خروجی مسیرهای مدیریت آگهی‌های شغلی (Job Service).
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import strip_html_tags


class JobCreateRequest(BaseModel):
    """بدنه‌ی درخواست ساخت آگهی شغلی جدید."""

    title: str = Field(min_length=2, max_length=255)
    department: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    skills_required: list[str] = Field(default_factory=list)
    salary_range: Optional[str] = Field(default=None, max_length=50)
    # فیلدهای زیر اختیاری‌اند و برای موتور نمره‌دهی و رتبه‌بندی رزومه (Matching Score) استفاده می‌شوند
    required_seniority: Optional[str] = Field(default=None, max_length=50)
    required_education: Optional[str] = Field(default=None, max_length=50)
    location: Optional[str] = Field(default=None, max_length=100)

    @field_validator(
        "title", "department", "description", "salary_range", "required_seniority",
        "required_education", "location", mode="before",
    )
    @classmethod
    def sanitize_text_fields(cls, value):
        """پاکسازی هر فیلد متنی آزاد از تگ HTML/جاوااسکریپت پیش از پردازش (دفاع XSS)."""
        if isinstance(value, str):
            return strip_html_tags(value)
        return value

    @field_validator("skills_required", mode="before")
    @classmethod
    def sanitize_skills(cls, value):
        if isinstance(value, list):
            return [strip_html_tags(v) if isinstance(v, str) else v for v in value]
        return value


class JobResponse(BaseModel):
    """ساختار خروجی یک آگهی شغلی (هم برای ساخت، هم برای لیست)."""

    # validation_alias="id" یعنی: از روی آبجکت دیتابیس، مقدار را از فیلد id بخوان،
    # ولی در JSON خروجی همچنان با اسم job_id (طبق معیار پذیرش تسک) نمایش بده.
    job_id: uuid.UUID = Field(validation_alias="id")
    title: str
    department: Optional[str] = None
    description: Optional[str] = None
    skills_required: list[str] = Field(default_factory=list)
    salary_range: Optional[str] = None
    required_seniority: Optional[str] = None
    required_education: Optional[str] = None
    location: Optional[str] = None
    status: str
    created_by: uuid.UUID
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class JobListResponse(BaseModel):
    total: int
    items: list[JobResponse]
