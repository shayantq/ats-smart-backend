"""
ابزار رمزنگاری گذرواژه (Bcrypt) و صدور توکن‌های امنیتی (JWT).
"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

JWT_ALGORITHM = "HS256"

# schemes=["bcrypt"] یعنی همیشه از Bcrypt استفاده شود.
# deprecated="auto" باعث می‌شود اگر در آینده الگوریتم عوض شد، هش‌های قدیمی هم قابل تشخیص بمانند.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """گذرواژه‌ی خام را به یک رشته‌ی هش‌شده و غیرقابل بازگشت تبدیل می‌کند."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """گذرواژه‌ی وارد شده توسط کاربر (مثلاً هنگام لاگین) را با هش ذخیره‌شده مقایسه می‌کند."""
    return pwd_context.verify(plain_password, password_hash)


# ⚠️ Bcrypt عمداً کند است (~۲۰۰ میلی‌ثانیه CPU در هر بار، با ۱۲ دور). صدا زدنش مستقیم داخل یک
# endpoint از نوع async، کل Event Loop سرور را در همان مدت برای همه‌ی کاربران قفل می‌کند (یافته‌ی
# تست بار). نسخه‌های async زیر آن را در Thread Pool اجرا می‌کنند؛ چون کتابخانه‌ی bcrypt قفل GIL را
# آزاد می‌کند، چند هش هم‌زمان واقعاً موازی روی هسته‌های مختلف CPU انجام می‌شوند.
async def hash_password_async(plain_password: str) -> str:
    return await run_in_threadpool(hash_password, plain_password)


async def verify_password_async(plain_password: str, password_hash: str) -> bool:
    return await run_in_threadpool(verify_password, plain_password, password_hash)


# هش یک گذرواژه‌ی تصادفی، فقط برای «ورود با ایمیل ناموجود»: تا زمان پاسخ با حالت «رمز اشتباه»
# یکسان باشد و مهاجم نتواند از روی تفاوت زمان، ایمیل‌های ثبت‌شده را حدس بزند (Timing Attack)
_DUMMY_PASSWORD_HASH = pwd_context.hash("timing-attack-equalizer")


async def verify_login_password_async(plain_password: str, password_hash: str | None) -> bool:
    """مثل verify_password_async، ولی اگر کاربر وجود نداشته باشد هم همان مقدار کار را انجام می‌دهد."""
    if password_hash is None:
        await verify_password_async(plain_password, _DUMMY_PASSWORD_HASH)
        return False
    return await verify_password_async(plain_password, password_hash)


def _create_token(
    subject: str, expires_delta: timedelta, token_type: str, extra_claims: dict | None = None
) -> tuple[str, int]:
    """
    تابع مشترک داخلی برای ساخت هر دو نوع توکن.
    subject: معمولاً شناسه‌ی (id) کاربر است.
    token_type: "access" یا "refresh"، تا در آینده بشود دو نوع توکن را از هم تشخیص داد.
    خروجی: (خودِ توکن، طول عمر توکن به ثانیه)
    """
    expire_at = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": subject, "exp": expire_at, "type": token_type, **(extra_claims or {})}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, int(expires_delta.total_seconds())


def create_access_token(
    subject: str, tenant_id: uuid.UUID | str | None = None, session_id: str | None = None
) -> tuple[str, int]:
    """
    توکن دسترسی با طول عمر کوتاه (پیش‌فرض ۱۵ دقیقه، طبق تنظیمات .env).
    tenant_id: سازمان کارمند، به‌صورت Claim «tid» — منبع Context چندمستاجری (app/core/tenancy.py).
    چون توکن امضاشده است، کاربر نمی‌تواند سازمانش را عوض کند؛ کارجو این Claim را ندارد.
    session_id: نشست صادرکننده (Claim «sid»)؛ با ابطال نشست، این توکن هم فوراً رد می‌شود (app/core/deps.py).
    """
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {}
    if tenant_id:
        claims["tid"] = str(tenant_id)
    if session_id:
        claims["sid"] = session_id
    return _create_token(subject, expires_delta, token_type="access", extra_claims=claims)


def create_refresh_token(subject: str, session_id: str | None = None, jti: str | None = None) -> tuple[str, int]:
    """
    توکن نوسازی با طول عمر بلند (پیش‌فرض ۷ روز، طبق تنظیمات .env).
    sid: نشست ذخیره‌شده در Redis؛ jti: شناسه‌ی یکتای همین نسخه از توکن (هر نوسازی jti تازه می‌گیرد و
    jti قبلی در فهرست سیاه می‌رود — بنگرید app/core/sessions.py).
    """
    expires_delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    claims = {"sid": session_id, "jti": jti} if session_id else None
    return _create_token(subject, expires_delta, token_type="refresh", extra_claims=claims)


def decode_token(token: str) -> dict:
    """
    رمزگشایی و اعتبارسنجی یک توکن JWT (امضا و تاریخ انقضا).
    اگر توکن نامعتبر یا منقضی باشد، jose.JWTError پرتاب می‌شود؛
    مسئولیت گرفتنِ این خطا و برگرداندن پاسخ مناسب (401) با لایه‌ی بالاتر است.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
