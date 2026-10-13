"""
اتصال async به دیتابیس PostgreSQL و تولید Session برای هر درخواست.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    # اتصال‌های قطع‌شده (مثلاً بعد از ری‌استارت دیتابیس) پیش از استفاده شناسایی و جایگزین می‌شوند
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency برای FastAPI: یک Session جدید باز می‌کند، در اختیار endpoint می‌گذارد
    و در پایان درخواست (چه موفق چه ناموفق) آن را می‌بندد.
    """
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def worker_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """
    Session برای کارهای پس‌زمینه‌ی Worker که هر کدام با asyncio.run() در یک event loop تازه اجرا
    می‌شوند. اتصال‌های asyncpg به loop سازنده‌شان گره خورده‌اند؛ اگر کار بعدی از Pool مشترک بالا
    (ساخته‌شده در loop کار قبلی) استفاده کند، با «attached to a different loop» شکست می‌خورد.
    پس هر کار Engine خودش را بدون Pool می‌سازد و در پایان همان loop می‌بندد.
    """
    task_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        yield async_sessionmaker(bind=task_engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await task_engine.dispose()
