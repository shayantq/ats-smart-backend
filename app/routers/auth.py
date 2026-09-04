"""
مسیرهای ارتباطی احراز هویت: ثبت‌نام (Public) و ورود (Public).
هر دو مسیر تحت محدودیت نرخ درخواست (Rate Limit) هستند تا در برابر
حملات حدس رمز عبور (Brute-Force) و DDOS محافظت شوند.
"""

import asyncio
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cached, get_cached_json, set_cached_json
from app.core.config import settings
from app.core.limiter import limiter
from app.core.notification_service import notify_new_user_registered
from app.core.queue import enqueue_task
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    RegisterResponseData,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.tasks.notifications import send_otp_email_task

router = APIRouter()

# مدت اعتبار کد OTP بازیابی رمز عبور
_OTP_TTL_SECONDS = 600  # ۱۰ دقیقه
_OTP_CACHE_KEY_PREFIX = "password_reset_otp:"


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    summary="ثبت‌نام کاربر جدید در پلتفرم",
)
@limiter.limit("5/minute")
async def register_user(
    request: Request,
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """
    ثبت‌نام کاربر جدید:
    - اگر ایمیل قبلاً ثبت شده باشد، خطای 400 برمی‌گرداند.
    - گذرواژه هرگز به‌صورت متن آشکار ذخیره نمی‌شود؛ همیشه با Bcrypt هش می‌شود.
    """
    # بررسی تکراری نبودن ایمیل پیش از ثبت کاربر نهایی
    existing_user_result = await db.execute(select(User).where(User.email == payload.email))
    existing_user = existing_user_result.scalar_one_or_none()

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="کاربری با این ایمیل قبلاً ثبت‌نام کرده است.",
        )

    new_user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role.value,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # محرک (Trigger) زیرسیستم اطلاع‌رسانی: ارسال ایمیل خوش‌آمدگویی/تأیید اصالت.
    # عمداً با create_task (نه await مستقیم) تا این درخواست ثبت‌نام هیچ‌وقت
    # معطل ارتباط با Redis یا ارسال واقعی ایمیل نماند و پاسخ فوراً صادر شود.
    asyncio.create_task(notify_new_user_registered(new_user.email))

    return RegisterResponse(
        status="success",
        message="User registered successfully",
        data=RegisterResponseData(
            user_id=new_user.id,
            email=new_user.email,
            role=new_user.role,
            created_at=new_user.created_at,
        ),
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    tags=["Auth"],
    summary="ورود کاربر و صدور توکن‌های دسترسی",
)
@limiter.limit("5/minute")
async def login_user(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    ورود کاربر با ایمیل و گذرواژه:
    - اگر ایمیل وجود نداشت یا گذرواژه اشتباه بود، خطای 401 برمی‌گرداند
      (پیام خطا عمداً یکسان است تا مهاجم نفهمد کدام‌یک اشتباه بوده).
    - در صورت موفقیت، یک access_token کوتاه‌مدت و یک refresh_token بلندمدت صادر می‌شود.
    - refresh_token علاوه بر بدنه‌ی پاسخ، در یک کوکی HttpOnly + Secure هم ست می‌شود
      تا در برابر دسترسی جاوااسکریپت مخرب (XSS) محافظت شود.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ایمیل یا گذرواژه نادرست است.",
        )

    access_token, expires_in = create_access_token(subject=str(user.id))
    refresh_token, refresh_max_age = create_refresh_token(subject=str(user.id))

    # تنظیم Refresh Token در قالب کوکی امن (نه در دسترس جاوااسکریپت فرانت‌اند)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=refresh_max_age,
        path=f"{settings.API_V1_PREFIX}/auth",
    )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


def _generate_otp_code() -> str:
    """یک کد ۶ رقمی امن (با secrets، نه random معمولی) تولید می‌کند."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def _issue_and_send_password_reset_otp(email: str) -> None:
    """
    کد OTP را تولید، در Redis با TTL محدود ذخیره، و Task ارسال ایمیل مربوطه
    را به صف اضافه می‌کند. همیشه با asyncio.create_task فراخوانی می‌شود
    (fire-and-forget) تا پاسخ /forgot-password هیچ‌وقت معطل این کارها نماند.
    """
    otp_code = _generate_otp_code()
    await set_cached_json(f"{_OTP_CACHE_KEY_PREFIX}{email}", {"otp": otp_code}, ttl_seconds=_OTP_TTL_SECONDS)
    await enqueue_task(send_otp_email_task, email, otp_code, _OTP_TTL_SECONDS // 60)


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
    tags=["Auth"],
    summary="درخواست بازیابی رمز عبور — ارسال کد OTP به ایمیل",
)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """
    همیشه یک پیام یکسان برمی‌گرداند (چه ایمیل در سیستم ثبت شده باشد چه نه)
    تا این مسیر نتواند برای حدس زدن ایمیل‌های موجود در سیستم استفاده شود
    (User Enumeration). اگر ایمیل واقعاً وجود داشت، کد OTP فقط در پس‌زمینه
    (بدون معطل کردن این پاسخ) تولید، در Redis ذخیره، و ایمیل می‌شود.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is not None:
        asyncio.create_task(_issue_and_send_password_reset_otp(user.email))

    return ForgotPasswordResponse(
        message="اگر این ایمیل در سیستم ثبت شده باشد، کد بازیابی برایش ارسال خواهد شد."
    )


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    status_code=status.HTTP_200_OK,
    tags=["Auth"],
    summary="تکمیل بازیابی رمز عبور با کد OTP دریافتی از ایمیل",
)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ResetPasswordResponse:
    """
    کد OTP ارسالی را با مقدار ذخیره‌شده در Redis مقایسه می‌کند (که پیش‌تر
    توسط /forgot-password ساخته شده). اگر معتبر بود، گذرواژه‌ی کاربر با
    Bcrypt هش و جایگزین می‌شود و کد OTP بلافاصله باطل (حذف) می‌شود تا
    یک‌بارمصرف بودنش تضمین شود.
    """
    cache_key = f"{_OTP_CACHE_KEY_PREFIX}{payload.email}"
    cached_otp = await get_cached_json(cache_key)

    if cached_otp is None or cached_otp.get("otp") != payload.otp_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="کد بازیابی نامعتبر یا منقضی‌شده است.",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None:
        # عملاً نباید اتفاق بیفتد (چون OTP فقط برای ایمیل‌های واقعی صادر می‌شود)،
        # ولی برای اطمینان کامل، همان پیام عمومی خطا برگردانده می‌شود.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="کد بازیابی نامعتبر یا منقضی‌شده است.",
        )

    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    await db.commit()

    # ابطال فوری کد OTP بعد از مصرف موفق — تضمین یک‌بارمصرف بودن
    await delete_cached(cache_key)

    return ResetPasswordResponse(message="رمز عبور با موفقیت تغییر یافت.")
