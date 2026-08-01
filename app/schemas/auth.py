"""
اسکیمای ورودی و خروجی مسیر ثبت‌نام کاربر (POST /api/v1/auth/register).
"""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    """نقش‌های مجاز کاربری، دقیقاً منطبق با جدول Roles در مستند دیتابیس."""

    ADMIN = "Admin"
    HR_MANAGER = "HR_Manager"
    INTERVIEWER = "Interviewer"
    CANDIDATE = "Candidate"


class RegisterRequest(BaseModel):
    """بدنه‌ی درخواست ثبت‌نام. Pydantic خودکار فرمت ایمیل و طول گذرواژه را اعتبارسنجی می‌کند."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="حداقل ۸ کاراکتر")
    role: UserRole


class RegisterResponseData(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    role: str
    created_at: datetime


class RegisterResponse(BaseModel):
    """ساختار پاسخ موفق ثبت‌نام، منطبق با قرارداد API مستندشده در طراحی سیستم."""

    status: str
    message: str
    data: RegisterResponseData
