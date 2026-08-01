"""
اتصال async به دیتابیس PostgreSQL و تولید Session برای هر درخواست.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)

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
