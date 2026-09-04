"""
اسکیمای ورودی و خروجی مسیر ثبت‌نام کاربر (POST /api/v1/auth/register).
"""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.sanitize import strip_html_tags


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

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email(cls, value: str) -> str:
        """پیش از اعتبارسنجی فرمت ایمیل، هر تگ HTML/جاوااسکریپت احتمالی را حذف می‌کند (دفاع XSS)."""
        return strip_html_tags(value)


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


class LoginRequest(BaseModel):
    """بدنه‌ی درخواست ورود."""

    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email(cls, value: str) -> str:
        return strip_html_tags(value)


class LoginResponse(BaseModel):
    """
    ساختار پاسخ موفق ورود.
    توجه: refresh_token علاوه بر این‌که در بدنه‌ی پاسخ برگردانده می‌شود
    (طبق قرارداد مستندشده‌ی API)، در یک کوکی HttpOnly و Secure نیز ست می‌شود.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ForgotPasswordRequest(BaseModel):
    """بدنه‌ی درخواست بازیابی رمز عبور — فقط ایمیل لازم است."""

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email(cls, value: str) -> str:
        return strip_html_tags(value)


class ForgotPasswordResponse(BaseModel):
    """
    پیام همیشه یکسان است (چه ایمیل در سیستم ثبت شده باشد چه نه) تا این مسیر
    نتواند برای حدس زدن ایمیل‌های موجود در سیستم استفاده شود (User Enumeration).
    """

    message: str


class ResetPasswordRequest(BaseModel):
    """بدنه‌ی درخواست تکمیل بازیابی رمز عبور با کد OTP دریافتی از ایمیل."""

    email: EmailStr
    otp_code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email(cls, value: str) -> str:
        return strip_html_tags(value)

    @field_validator("otp_code", mode="before")
    @classmethod
    def sanitize_otp(cls, value: str) -> str:
        if isinstance(value, str):
            return strip_html_tags(value)
        return value


class ResetPasswordResponse(BaseModel):
    message: str
