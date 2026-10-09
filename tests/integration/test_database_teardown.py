"""
اثبات معیار پذیرش «دیتابیس تست مجزا + پاکسازی داده‌های موقت (Teardown)».
"""

import pytest
from sqlalchemy import func, select, text

from app.models import Job, User


async def test_tests_run_on_a_separate_temporary_database(db_session):
    """تست‌ها هرگز روی دیتابیس اصلی توسعه اجرا نمی‌شوند — نام دیتابیس جاری شامل _test_ است."""
    current_database = (await db_session.execute(text("SELECT current_database()"))).scalar_one()
    assert "_test_" in current_database


async def test_schema_comes_from_real_alembic_migrations(db_session):
    """اسکیمای دیتابیس تست همان اسکیمای Production است (کل زنجیره‌ی مایگریشن‌ها اجرا شده)."""
    version = (await db_session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert version == "b5e2c9d4a710"
    gin_index = await db_session.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_resumes_raw_text_fts_v2'")
    )
    assert gin_index.scalar_one_or_none() == 1


# دو اجرای پشت‌سرهم یک تست: هرکدام اول بررسی می‌کند دیتابیس خالی است و بعد داده می‌سازد.
# اگر Teardown اجرای اول کار نمی‌کرد، اجرای دوم داده‌های آن را می‌دید و Fail می‌شد.
@pytest.mark.parametrize("run", ["first", "second"])
async def test_each_test_starts_with_empty_tables_and_leaves_no_data(db_session, make_user, run):
    assert (await db_session.execute(select(func.count()).select_from(User))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(Job))).scalar_one() == 0

    creator = await make_user(role="HR_Manager")
    db_session.add(Job(title=f"Teardown probe ({run})", created_by=creator.id))
    await db_session.commit()

    assert (await db_session.execute(select(func.count()).select_from(Job))).scalar_one() == 1
