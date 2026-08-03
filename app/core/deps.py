"""
لایه‌ی کنترل دسترسی (RBAC):
- get_current_user: توکن را از هدر Authorization می‌خواند، اعتبارسنجی می‌کند و کاربر را برمی‌گرداند.
- require_roles: یک Dependency Factory که مسیر را فقط به نقش‌های مشخص‌شده باز می‌گذارد.
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models import User

# auto_error=False عمداً غیرفعال شده: می‌خواهیم خودمان دقیقاً کد 401 برگردانیم
# (رفتار پیش‌فرض HTTPBearer برای عدم ارسال توکن، کد 403 است که با معیار پذیرش تسک همخوانی ندارد)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    این Dependency روی هر مسیر محافظت‌شده قرار می‌گیرد و پیش از اجرای خودِ endpoint,
    توکن کاربر را رمزگشایی کرده و کاربر متناظرش را از دیتابیس برمی‌گرداند.
    اگر توکن نبود، نامعتبر بود، یا کاربرش پیدا نشد -> خطای 401.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="توکن معتبر ارسال نشده یا منقضی شده است.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise unauthorized

    # فقط access_token اجازه‌ی دسترسی به منابع را دارد (refresh_token برای این کار نیست)
    if payload.get("type") != "access":
        raise unauthorized

    user_id = payload.get("sub")
    if user_id is None:
        raise unauthorized

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise unauthorized

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if user is None:
        raise unauthorized

    return user


def require_roles(*allowed_roles: str):
    """
    Dependency Factory برای محدود کردن یک مسیر به نقش‌های مشخص.

    نمونه‌ی استفاده:
        @router.get("/stats", dependencies=[Depends(require_roles("Admin"))])
    """

    async def _role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="شما اجازه‌ی دسترسی به این بخش را ندارید.",
            )
        return current_user

    return _role_checker
