"""
ابزار رمزنگاری گذرواژه (Bcrypt) و صدور توکن‌های امنیتی (JWT).
"""

from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

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


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> tuple[str, int]:
    """
    تابع مشترک داخلی برای ساخت هر دو نوع توکن.
    subject: معمولاً شناسه‌ی (id) کاربر است.
    token_type: "access" یا "refresh"، تا در آینده بشود دو نوع توکن را از هم تشخیص داد.
    خروجی: (خودِ توکن، طول عمر توکن به ثانیه)
    """
    expire_at = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": subject, "exp": expire_at, "type": token_type}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, int(expires_delta.total_seconds())


def create_access_token(subject: str) -> tuple[str, int]:
    """توکن دسترسی با طول عمر کوتاه (پیش‌فرض ۱۵ دقیقه، طبق تنظیمات .env)."""
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_token(subject, expires_delta, token_type="access")


def create_refresh_token(subject: str) -> tuple[str, int]:
    """توکن نوسازی با طول عمر بلند (پیش‌فرض ۷ روز، طبق تنظیمات .env)."""
    expires_delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _create_token(subject, expires_delta, token_type="refresh")
