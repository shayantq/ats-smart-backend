"""
مسیر ارتباطی ثبت‌نام کاربران جدید (Public).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import RegisterRequest, RegisterResponse, RegisterResponseData

router = APIRouter()


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    summary="ثبت‌نام کاربر جدید در پلتفرم",
)
async def register_user(
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
