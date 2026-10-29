"""
اسکیمای ورودی و خروجی مسیر ثبت‌نام کاربر (POST /api/v1/auth/register).
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.sanitize import strip_html_tags


class UserRole(str, Enum):
    """نقش‌های مجاز کاربری، دقیقاً منطبق با جدول Roles در مستند دیتابیس."""

    ADMIN = "Admin"
    HR_MANAGER = "HR_Manager"
    INTERVIEWER = "Interviewer"
    CANDIDATE = "Candidate"


class RegisterRequest(BaseModel):
    """
    بدنه‌ی درخواست ثبت‌نام. Pydantic خودکار فرمت ایمیل و طول گذرواژه را اعتبارسنجی می‌کند.

    چندمستاجری: ثبت‌نام Admin یک سازمان (Tenant) تازه با نام company_name می‌سازد و Admin مالک آن
    می‌شود. حساب HR_Manager و Interviewer ثبت‌نام عمومی ندارد؛ Admin همان سازمان آن را از مسیر
    POST /api/v1/tenant/users می‌سازد تا هیچ کارمندی بدون سازمان در سیستم نباشد.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="حداقل ۸ کاراکتر")
    role: UserRole
    company_name: Optional[str] = Field(
        default=None, min_length=2, max_length=255, description="فقط برای Admin: نام سازمان جدید"
    )
    # حریم خصوصی: کارجو باید رضایت‌نامه‌ی پردازش داده‌های شخصی را صریحاً تأیید کند؛ زمان و نسخه‌ی متن
    # رضایت‌نامه سمت سرور ثبت می‌شود (users.data_consent_at / data_consent_version)
    data_consent: bool = Field(default=False, description="تأیید رضایت‌نامه‌ی پردازش داده‌های شخصی (برای کارجو الزامی)")

    @field_validator("company_name", mode="before")
    @classmethod
    def sanitize_company_name(cls, value):
        return strip_html_tags(value).strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def check_tenant_onboarding(self) -> "RegisterRequest":
        if self.role in (UserRole.HR_MANAGER, UserRole.INTERVIEWER):
            raise ValueError("حساب HR و مصاحبه‌کننده را Admin سازمان از مسیر POST /api/v1/tenant/users می‌سازد.")
        if self.role == UserRole.ADMIN and not self.company_name:
            raise ValueError("برای ثبت‌نام Admin، نام سازمان (company_name) الزامی است.")
        if self.role == UserRole.CANDIDATE and self.company_name:
            raise ValueError("کارجو عضو سازمان نیست؛ company_name را نفرستید.")
        if self.role == UserRole.CANDIDATE and not self.data_consent:
            raise ValueError("برای ثبت‌نام کارجو، تأیید رضایت‌نامه‌ی پردازش داده‌های شخصی (data_consent) الزامی است.")
        return self

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
    tenant_id: Optional[uuid.UUID] = None


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


class CurrentUserResponse(BaseModel):
    """
    اطلاعات کاربر لاگین‌شده (GET /api/v1/auth/me) — فرانت‌اند بعد از ورود با آن تصمیم
    می‌گیرد کاربر را به کدام پورتال (داشبورد HR یا پورتال کارجو) هدایت کند.
    """

    user_id: uuid.UUID
    email: EmailStr
    role: str
    tenant_id: Optional[uuid.UUID] = None


class RefreshRequest(BaseModel):
    """بدنه‌ی اختیاری POST /api/v1/auth/refresh — مرورگر توکن را از کوکی HttpOnly می‌فرستد."""

    refresh_token: Optional[str] = None


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int


class SessionLocation(BaseModel):
    country: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None


class SessionResponse(BaseModel):
    """یک نشست فعال (دستگاه) کاربر — GET /api/v1/auth/sessions/"""

    id: str
    browser: str
    browser_version: str
    os: str
    os_version: str
    device_type: str
    device: str
    user_agent: str
    ip: str
    location: Optional[SessionLocation] = None
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime
    is_current: bool
    suspicious: bool

    @classmethod
    def from_store(cls, data: dict, current_session_id: str | None, mask_ip) -> "SessionResponse":
        """ردیف Hash نشست در Redis (app/core/sessions.py) → پاسخ API. IP نشست‌های دیگر نیمه‌پنهان است."""

        def timestamp(name: str) -> datetime:
            return datetime.fromtimestamp(float(data[name]), tz=timezone.utc)

        is_current = data["sid"] == current_session_id
        location = None
        if data.get("country_code"):
            location = SessionLocation(
                country=data.get("country") or None, country_code=data["country_code"], city=data.get("city") or None
            )
        return cls(
            id=data["sid"],
            browser=data.get("browser", ""),
            browser_version=data.get("browser_version", ""),
            os=data.get("os", ""),
            os_version=data.get("os_version", ""),
            device_type=data.get("device_type", ""),
            device=data.get("device", ""),
            user_agent=data.get("user_agent", ""),
            ip=data.get("ip", "") if is_current else mask_ip(data.get("ip")),
            location=location,
            created_at=timestamp("created_at"),
            last_active_at=timestamp("last_active_at"),
            expires_at=timestamp("expires_at"),
            is_current=is_current,
            suspicious=data.get("suspicious") == "1",
        )


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
