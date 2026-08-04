"""
مسیرهای ارتباطی احراز هویت: ثبت‌نام (Public) و ورود (Public).
هر دو مسیر تحت محدودیت نرخ درخواست (Rate Limit) هستند تا در برابر
حملات حدس رمز عبور (Brute-Force) و DDOS محافظت شوند.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    RegisterResponseData,
)

router = APIRouter()


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
