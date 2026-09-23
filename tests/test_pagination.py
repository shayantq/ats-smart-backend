"""
تست منطق صفحه‌بندی مبتنی بر نشانگر (Cursor Pagination) در app/core/pagination.py.

طبق معیارهای پذیرش تسک، این تست‌ها تضمین می‌کنند که:
- رمزگذاری/رمزگشایی cursor بدون افت اطلاعات (Round-Trip) کار می‌کند.
- ورق‌زدن رو به جلو (direction=next) هیچ رکوردی را جا نمی‌اندازد و تکرار نمی‌کند.
- ورق‌زدن رو به عقب (direction=prev) دقیقاً همان ترتیب اصلی را بازسازی می‌کند.
- ترتیب صعودی (descending=False، مثل لیست مصاحبه‌ها) هم درست کار می‌کند.
- یک cursor نامعتبر/دستکاری‌شده باعث خطای HTTP 400 (نه کرش سرور) می‌شود.

از یک دیتابیس SQLite در حافظه (aiosqlite) استفاده شده تا این تست‌ها بدون
نیاز به یک PostgreSQL واقعی در دسترس اجرا شوند؛ pagination.py هیچ syntax
مخصوص PostgreSQL در پایتون ندارد (فقط از tuple_() استاندارد SQLAlchemy
استفاده می‌کند)، پس همین پوشش برای اطمینان از درستی منطق کافی است.
"""

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.pagination import CursorParams, decode_cursor, encode_cursor, paginate_by_cursor


class _Base(DeclarativeBase):
    pass


class _DummyJob(_Base):
    """یک جدول کوچک و مستقل فقط برای تست pagination — به مدل‌های واقعی پروژه وابسته نیست."""

    __tablename__ = "dummy_jobs_for_pagination_test"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)

    base_time = datetime(2026, 1, 1)
    row_ids = [uuid.uuid4() for _ in range(25)]
    async with AsyncSession(engine) as session:
        for index, row_id in enumerate(row_ids):
            session.add(_DummyJob(id=row_id, title=f"job-{index}", created_at=base_time + timedelta(minutes=index)))
        await session.commit()

    async with AsyncSession(engine) as session:
        yield session, row_ids

    await engine.dispose()


def test_cursor_round_trip_datetime_and_uuid():
    """رمزگذاری و رمزگشایی یک cursor باید دقیقاً همان مقدار اصلی را برگرداند."""
    original_value = datetime(2026, 5, 1, 12, 30)
    original_id = uuid.uuid4()

    token = encode_cursor(original_value, original_id)
    decoded_value, decoded_id = decode_cursor(token)

    assert decoded_value == original_value
    assert decoded_id == original_id


@pytest.mark.asyncio
async def test_forward_pagination_has_no_duplicates_or_gaps(db_session):
    """ورق‌زدن کامل رو به جلو باید دقیقاً همه‌ی ۲۵ رکورد را یک‌بار و به ترتیب صحیح برگرداند."""
    session, row_ids = db_session
    query = sa.select(_DummyJob)

    seen_ids: list[uuid.UUID] = []
    cursor = None
    while True:
        page = await paginate_by_cursor(
            session,
            query,
            sort_column=_DummyJob.created_at,
            id_column=_DummyJob.id,
            params=CursorParams(cursor=cursor, direction="next", limit=10),
            descending=True,
        )
        seen_ids.extend(item.id for item in page.items)
        if not page.has_next:
            assert page.next_cursor is None
            break
        cursor = page.next_cursor

    assert len(seen_ids) == 25
    assert len(set(seen_ids)) == 25  # بدون رکورد تکراری
    assert seen_ids[0] == row_ids[24]  # جدیدترین (created_at بزرگ‌تر) اول
    assert seen_ids[-1] == row_ids[0]


@pytest.mark.asyncio
async def test_backward_pagination_reconstructs_same_order(db_session):
    """با previous_cursor از آخرین صفحه، باید بتوان دقیقاً به همان ترتیب اصلی برگشت."""
    session, _ = db_session
    query = sa.select(_DummyJob)

    forward_ids: list[uuid.UUID] = []
    cursor = None
    last_page = None
    while True:
        page = await paginate_by_cursor(
            session,
            query,
            sort_column=_DummyJob.created_at,
            id_column=_DummyJob.id,
            params=CursorParams(cursor=cursor, direction="next", limit=10),
            descending=True,
        )
        forward_ids.extend(item.id for item in page.items)
        last_page = page
        if not page.has_next:
            break
        cursor = page.next_cursor

    backward_ids = list(reversed([item.id for item in last_page.items]))
    cursor = last_page.previous_cursor
    while cursor is not None:
        page = await paginate_by_cursor(
            session,
            query,
            sort_column=_DummyJob.created_at,
            id_column=_DummyJob.id,
            params=CursorParams(cursor=cursor, direction="prev", limit=10),
            descending=True,
        )
        backward_ids.extend(reversed([item.id for item in page.items]))
        cursor = page.previous_cursor
    backward_ids.reverse()

    assert backward_ids == forward_ids


@pytest.mark.asyncio
async def test_ascending_order_pagination(db_session):
    """برای لیست‌هایی مثل مصاحبه‌ها که قدیمی‌ترین باید اول باشد (descending=False)."""
    session, row_ids = db_session
    query = sa.select(_DummyJob)

    page = await paginate_by_cursor(
        session,
        query,
        sort_column=_DummyJob.created_at,
        id_column=_DummyJob.id,
        params=CursorParams(cursor=None, direction="next", limit=5),
        descending=False,
    )

    assert [item.id for item in page.items] == row_ids[:5]
    assert page.has_next is True
    assert page.has_previous is False


@pytest.mark.asyncio
async def test_invalid_cursor_raises_http_400(db_session):
    """یک توکن cursor خراب/دستکاری‌شده نباید سرور را کرش کند؛ باید 400 برگرداند."""
    session, _ = db_session
    query = sa.select(_DummyJob)

    with pytest.raises(HTTPException) as exc_info:
        await paginate_by_cursor(
            session,
            query,
            sort_column=_DummyJob.created_at,
            id_column=_DummyJob.id,
            params=CursorParams(cursor="this-is-not-a-valid-cursor", direction="next", limit=10),
            descending=True,
        )

    assert exc_info.value.status_code == 400
