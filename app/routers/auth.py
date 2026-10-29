"""
مسیرهای ارتباطی احراز هویت: ثبت‌نام (Public) و ورود (Public).
هر دو مسیر تحت محدودیت نرخ درخواست (Rate Limit) هستند تا در برابر
حملات حدس رمز عبور (Brute-Force) و DDOS محافظت شوند.

مدیریت نشست‌ها (app/core/sessions.py): هر ورود یک نشست در Redis می‌سازد؛ نوسازی توکن (/refresh)،
فهرست دستگاه‌ها (/sessions/)، خروج از دستگاه‌های دیگر (DELETE /sessions/{id}/) و خروج (/logout).
"""

import asyncio
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cached, get_cached_json, set_cached_json
from app.core.config import settings
from app.core.deps import get_current_session_id, get_current_user
from app.core.limiter import limiter
from app.core.notification_service import notify_new_user_registered
from app.core.queue import enqueue_task
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    verify_login_password_async,
)
from app.core.sessions import (
    CreatedSession,
    SessionInvalid,
    SessionStoreUnavailable,
    create_session,
    list_sessions,
    mask_ip,
    revoke_session,
    rotate_refresh,
)
from app.core.tenancy import system_scope
from app.core.tenant_provisioning import provision_tenant
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    CurrentUserResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    RegisterResponseData,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SessionListResponse,
    SessionResponse,
)
from app.tasks.notifications import (
    send_new_signin_email_task,
    send_otp_email_task,
    send_suspicious_login_email_task,
)

router = APIRouter()

# مدت اعتبار کد OTP بازیابی رمز عبور
_OTP_TTL_SECONDS = 600  # ۱۰ دقیقه
_OTP_CACHE_KEY_PREFIX = "password_reset_otp:"

REFRESH_COOKIE_NAME = "refresh_token"
# ساعت ایران (بدون ساعت تابستانی از ۱۴۰۱) برای زمان ورود در ایمیل هشدار
_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def _session_store_unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="سرویس نشست موقتاً در دسترس نیست.")


def _set_refresh_cookie(response: Response, refresh_token: str, max_age: int) -> None:
    """Refresh Token در کوکی HttpOnly + Secure (در دسترس جاوااسکریپت فرانت‌اند نیست)."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=max_age,
        path=f"{settings.API_V1_PREFIX}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME, path=f"{settings.API_V1_PREFIX}/auth", secure=True, httponly=True, samesite="strict"
    )


async def _enqueue_login_alerts(email: str, created: CreatedSession) -> None:
    """
    ایمیل هشدار امنیتی ورود در صف Redis (ارسال واقعی با Worker؛ ورود هرگز معطل SMTP نمی‌ماند):
    ورود مشکوک → «Suspicious Login»؛ وگرنه مرورگر/IP تازه → «ورود از دستگاه جدید». اولین ورود → هیچ.
    """
    assessment, data = created.assessment, created.data
    if not (assessment.suspicious or assessment.should_alert_new_device):
        return
    signed_in_at = datetime.fromtimestamp(float(data["created_at"]), tz=_IRAN_TZ)
    details = {
        "signed_in_at": f"{signed_in_at:%Y-%m-%d %H:%M} (Tehran)",
        "browser": f"{data['browser']} {data['browser_version']}".strip(),
        "os": f"{data['os']} {data['os_version']}".strip(),
        "ip": data["ip"],
        "location": created.geo.label if created.geo else "نامشخص",
        "sessions_url": f"{settings.FRONTEND_ORIGIN.rstrip('/')}/?view=sessions",
    }
    if assessment.suspicious:
        await enqueue_task(send_suspicious_login_email_task, email, details, assessment.reasons)
    else:
        await enqueue_task(send_new_signin_email_task, email, details)


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
        password_hash=await hash_password_async(payload.password),
        role=payload.role.value,
    )

    if payload.company_name:
        # ثبت‌نام Admin = ساخت سازمان (Tenant) تازه. ساخت سازمان کار سطح پلتفرم است و هیچ پالیسی
        # RLS ی اجازه‌اش را به نقش درخواست‌ها نمی‌دهد؛ پس فقط همین بخش صریحاً در حالت system اجرا می‌شود.
        async with system_scope(db):
            await provision_tenant(db, name=payload.company_name, owner=new_user)
            await db.commit()
    else:
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
            tenant_id=new_user.tenant_id,
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

    # Bcrypt در Thread Pool (بدون قفل کردن سرور) و با زمان یکسان برای ایمیل ناموجود — بنگرید security.py
    if not await verify_login_password_async(payload.password, user.password_hash if user else None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ایمیل یا گذرواژه نادرست است.",
        )

    # نشست تازه در Redis: IP، مرورگر، سیستم‌عامل، موقعیت، زمان — Refresh Token فقط با همین نشست معتبر است
    try:
        created = await create_session(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id) if user.tenant_id else None,
            ip=get_remote_address(request),
            user_agent=request.headers.get("user-agent"),
        )
    except SessionStoreUnavailable:
        raise _session_store_unavailable()

    # tid (سازمان کارمند) و sid (نشست) داخل توکن امضاشده — منبع Context چندمستاجری هر درخواست بعدی
    access_token, expires_in = create_access_token(
        subject=str(user.id), tenant_id=user.tenant_id, session_id=created.session_id
    )
    refresh_token, refresh_max_age = create_refresh_token(
        subject=str(user.id), session_id=created.session_id, jti=created.refresh_jti
    )
    _set_refresh_cookie(response, refresh_token, refresh_max_age)

    await _enqueue_login_alerts(user.email, created)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


def _refresh_rejected(detail: str = "نشست شما پایان یافته است؛ لطفاً دوباره وارد شوید.") -> JSONResponse:
    """401 همراه با پاک کردن کوکی — فرانت‌اند کاربر را به صفحه‌ی ورود می‌برد."""
    rejected = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": detail}, headers={"WWW-Authenticate": "Bearer"}
    )
    _clear_refresh_cookie(rejected)
    return rejected


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    tags=["Auth"],
    summary="نوسازی access_token با Refresh Token (کوکی یا بدنه) و چرخش Refresh Token",
    responses={401: {"description": "نشست باطل، منقضی یا Refresh Token تکراری — ورود دوباره"}},
)
@limiter.limit("30/minute")
async def refresh_access_token(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    - Refresh Token از کوکی HttpOnly (مرورگر) یا بدنه‌ی درخواست (کلاینت‌های دیگر) خوانده می‌شود.
    - نشستش باید در Redis باشد و jti آن همان jti فعلی نشست باشد؛ jti قبلی در فهرست سیاه می‌رود و
      Refresh Token تازه صادر می‌شود (Rotation).
    - نشست باطل‌شده (DELETE /sessions/{id}/)، jti در فهرست سیاه، استفاده‌ی دوباره از توکن قدیمی (که کل
      نشست را باطل می‌کند) یا توکن قدیمی بدون sid → 401 و پاک شدن کوکی.
    """
    token = (payload.refresh_token if payload else None) or request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        return _refresh_rejected("Refresh Token ارسال نشده است.")
    try:
        claims = decode_token(token)
    except JWTError:
        return _refresh_rejected()
    if claims.get("type") != "refresh" or not claims.get("sid") or not claims.get("jti") or not claims.get("sub"):
        return _refresh_rejected()

    try:
        outcome = await rotate_refresh(session_id=claims["sid"], jti=claims["jti"], user_id=claims["sub"])
    except SessionInvalid:
        return _refresh_rejected()
    except SessionStoreUnavailable:
        raise _session_store_unavailable()

    user = (await db.execute(select(User).where(User.id == uuid.UUID(claims["sub"])))).scalar_one_or_none()
    if user is None:
        await revoke_session(claims["sid"])
        return _refresh_rejected()

    access_token, expires_in = create_access_token(
        subject=str(user.id), tenant_id=user.tenant_id, session_id=claims["sid"]
    )
    new_refresh_token = None
    if outcome.new_refresh_jti:
        new_refresh_token, refresh_max_age = create_refresh_token(
            subject=str(user.id), session_id=claims["sid"], jti=outcome.new_refresh_jti
        )
        _set_refresh_cookie(response, new_refresh_token, refresh_max_age)
    return RefreshResponse(access_token=access_token, refresh_token=new_refresh_token, expires_in=expires_in)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Auth"],
    summary="خروج: ابطال نشست همین دستگاه",
)
async def logout(
    current_user: User = Depends(get_current_user),
    session_id: str = Depends(get_current_session_id),
) -> Response:
    try:
        await revoke_session(session_id, user_id=str(current_user.id))
    except SessionStoreUnavailable:
        raise _session_store_unavailable()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get(
    "/sessions/",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    tags=["Auth"],
    summary="فهرست دستگاه‌ها و نشست‌های فعال کاربر (مرورگر، سیستم‌عامل، IP، موقعیت، آخرین فعالیت)",
)
async def get_my_sessions(
    current_user: User = Depends(get_current_user),
    session_id: str = Depends(get_current_session_id),
) -> SessionListResponse:
    try:
        sessions = await list_sessions(str(current_user.id))
    except SessionStoreUnavailable:
        raise _session_store_unavailable()
    return SessionListResponse(items=[SessionResponse.from_store(row, session_id, mask_ip) for row in sessions])


@router.delete(
    "/sessions/{session_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Auth"],
    summary="خروج از یک دستگاه دیگر (Force Logout): ابطال فوری نشست و Refresh Token آن",
)
async def revoke_my_session(session_id: str, current_user: User = Depends(get_current_user)) -> Response:
    """
    Refresh Token آن نشست فوراً در فهرست سیاه Redis می‌رود: نوسازی بعدی همان دستگاه → 401 و access_token
    فعلی‌اش هم در درخواست بعدی رد می‌شود. نشست کاربر دیگر یا ناموجود → 404.
    """
    try:
        revoked = await revoke_session(session_id, user_id=str(current_user.id))
    except SessionStoreUnavailable:
        raise _session_store_unavailable()
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="نشست پیدا نشد.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_200_OK,
    tags=["Auth"],
    summary="اطلاعات کاربر لاگین‌شده (شناسه، ایمیل، نقش)",
)
async def get_me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    """فقط با access_token معتبر؛ بدون توکن یا با توکن نامعتبر/منقضی → 401."""
    return CurrentUserResponse(
        user_id=current_user.id, email=current_user.email, role=current_user.role, tenant_id=current_user.tenant_id
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

    return ForgotPasswordResponse(message="اگر این ایمیل در سیستم ثبت شده باشد، کد بازیابی برایش ارسال خواهد شد.")


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

    user.password_hash = await hash_password_async(payload.new_password)
    db.add(user)
    await db.commit()

    # ابطال فوری کد OTP بعد از مصرف موفق — تضمین یک‌بارمصرف بودن
    await delete_cached(cache_key)

    return ResetPasswordResponse(message="رمز عبور با موفقیت تغییر یافت.")
