"""
اسکیمای مسیرهای سازمان جاری (Tenant): /api/v1/tenant
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.sanitize import strip_html_tags


class StaffRole(str, Enum):
    """نقش‌هایی که Admin سازمان می‌تواند برای همکارانش بسازد."""

    HR_MANAGER = "HR_Manager"
    INTERVIEWER = "Interviewer"


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: Optional[str] = None
    owner_id: uuid.UUID


class StaffCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: StaffRole

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email(cls, value: str) -> str:
        return strip_html_tags(value)


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    tenant_id: uuid.UUID
    created_at: datetime


class StaffListResponse(BaseModel):
    items: list[StaffResponse]
