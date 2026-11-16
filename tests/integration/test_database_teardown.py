"""
اثبات معیار پذیرش «دیتابیس تست مجزا + پاکسازی داده‌های موقت (Teardown)».
"""

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from app.models import Job, User
from tests.integration.conftest import PROJECT_ROOT


async def test_tests_run_on_a_separate_temporary_database(db_session):
    """تست‌ها هرگز روی دیتابیس اصلی توسعه اجرا نمی‌شوند — نام دیتابیس جاری شامل _test_ است."""
    current_database = (await db_session.execute(text("SELECT current_database()"))).scalar_one()
    assert "_test_" in current_database


async def test_schema_comes_from_real_alembic_migrations(db_session):
    """اسکیمای دیتابیس تست تا آخرین migration مخزن بالا آمده است."""
    version = (await db_session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None and version == head
    nullable = (
        await db_session.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'applications' AND column_name = 'resume_id'"
            )
        )
    ).scalar_one()
    assert nullable == "YES"
    constraint = (
        await db_session.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'fk_applications_resume_id'")
        )
    ).scalar_one()
    assert "FOREIGN KEY (resume_id) REFERENCES resumes(id)" in constraint
    tables = await db_session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    dossier_tables = {
        "dossier_review_heads",
        "dossier_review_events",
        "dossier_analysis_versions",
        "dossier_reanalysis_batches",
    }
    assert {"interview_question_sets", "interview_questions"} | dossier_tables <= set(tables.scalars())
    processing_type = (
        await db_session.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'resumes' AND column_name = 'processing_state'"
            )
        )
    ).scalar_one()
    assert processing_type == "jsonb"
    # چندمستاجری: RLS روی جدول‌های عملیاتی فعال است
    rls_tables = await db_session.execute(
        text("SELECT relname FROM pg_class WHERE relrowsecurity AND relnamespace = 'public'::regnamespace")
    )
    assert {"jobs", "applications", "resumes", "interviews", "candidates", "skills"} | dossier_tables <= set(
        rls_tables.scalars()
    )
    indexes = await db_session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'resumes'"))
    names = set(indexes.scalars())
    assert {"ix_resumes_search_tokens_gin", "ix_resumes_skill_keys_gin", "ix_resumes_experience_years"} <= names
    assert "ix_resumes_raw_text_fts_v2" not in names  # متن رزومه رمزشده است؛ جستجو با ایندکس کور
    assert "ix_resumes_skill_analysis_gin" not in names  # ایندکس بلااستفاده‌ی قبلی حذف شده


# دو اجرای پشت‌سرهم یک تست: هرکدام اول بررسی می‌کند دیتابیس خالی است و بعد داده می‌سازد.
# اگر Teardown اجرای اول کار نمی‌کرد، اجرای دوم داده‌های آن را می‌دید و Fail می‌شد.
@pytest.mark.parametrize("run", ["first", "second"])
async def test_each_test_starts_with_empty_tables_and_leaves_no_data(db_session, make_user, run):
    assert (await db_session.execute(select(func.count()).select_from(User))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(Job))).scalar_one() == 0

    creator = await make_user(role="HR_Manager")
    db_session.add(Job(title=f"Teardown probe ({run})", created_by=creator.id, tenant_id=creator.tenant_id))
    await db_session.commit()

    assert (await db_session.execute(select(func.count()).select_from(Job))).scalar_one() == 1
