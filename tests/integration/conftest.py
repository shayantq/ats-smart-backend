"""
زیرساخت تست‌های یکپارچه‌سازی: API واقعی (HTTPX AsyncClient) + یک دیتابیس PostgreSQL موقت و جدا.

چرخه‌ی عمر دیتابیس تست:
    ۱. شروع جلسه‌ی تست: یک دیتابیس کاملاً جدید با نام یکتا (مثلاً smart_ats_db_test_1a2b3c4d)
       روی همان سرور PostgreSQL ساخته می‌شود — دیتابیس اصلی توسعه هرگز دست نمی‌خورد.
    ۲. کل زنجیره‌ی مایگریشن‌های واقعی Alembic روی آن اجرا می‌شود (همان اسکیمای Production،
       شامل ایندکس‌های GIN جستجوی متنی — نه یک اسکیمای تقریبی با create_all).
    ۳. هر تست داخل یک تراکنش بیرونی اجرا می‌شود؛ commit های خودِ API فقط SAVEPOINT را
       آزاد می‌کنند و در پایان هر تست کل تراکنش Rollback می‌شود (Teardown داده‌های موقت) —
       پس هر تست با یک دیتابیس خالی شروع می‌شود (بنگرید test_database_teardown.py).
    ۴. پایان جلسه‌ی تست: کل دیتابیس موقت DROP می‌شود.

آدرس سرور: متغیر محیطی TEST_DATABASE_URL، یا در نبودش همان DATABASE_URL (فقط برای اتصال به
سرور استفاده می‌شود؛ نام دیتابیس عوض می‌شود). اگر PostgreSQL در دسترس نباشد، تست‌های این پوشه
Skip می‌شوند — مگر TEST_DB_REQUIRED=1 تنظیم شده باشد (مثل CI) که در آن صورت Fail می‌شوند تا
هیچ‌وقت بی‌صدا اجرا نشده رد نشوند.

اثرات جانبی بیرون از دیتابیس (ایمیل/صف Redis/زمان‌بند یادآور/کش نشست/Rate Limit) در این
تست‌ها با جایگزین‌های بی‌اثر یا حافظه‌ای عوض می‌شوند تا تست‌ها قطعی و مستقل از Redis باشند.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import deps
from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password
from app.core.storage import LocalStorageBackend
from app.db.session import get_db
from app.main import app
from app.models import Application, Candidate, Job, User
from app.routers import applications as applications_router
from app.routers import auth as auth_router
from app.routers import interviews as interviews_router
from app.routers import resumes as resumes_router

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_PASSWORD = "Passw0rd!x"


# ---------------------------------------------------------------------------
# دیتابیس موقت (یک‌بار برای کل جلسه‌ی تست)
# ---------------------------------------------------------------------------
async def _run_on_maintenance_db(server_url: URL, sql: str) -> None:
    connection = await asyncpg.connect(
        host=server_url.host,
        port=server_url.port or 5432,
        user=server_url.username,
        password=server_url.password,
        database="postgres",
        timeout=10,
    )
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    server_url = make_url(os.environ.get("TEST_DATABASE_URL") or settings.DATABASE_URL)
    test_db_name = f"{server_url.database or 'ats'}_test_{uuid.uuid4().hex[:8]}"
    test_url = server_url.set(database=test_db_name)

    try:
        asyncio.run(_run_on_maintenance_db(server_url, f'CREATE DATABASE "{test_db_name}"'))
    except Exception as error:  # noqa: BLE001
        message = f"PostgreSQL برای تست‌های یکپارچه‌سازی در دسترس نیست ({type(error).__name__}: {error})"
        if os.environ.get("TEST_DB_REQUIRED") == "1":
            pytest.fail(message)
        pytest.skip(message)

    try:
        # مایگریشن در یک پردازه‌ی جدا: env.py ی Alembic آدرس را از DATABASE_URL می‌خواند و
        # خودش asyncio.run صدا می‌زند — جدا بودن پردازه از هر تداخلی با Event Loop تست جلوگیری می‌کند
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=PROJECT_ROOT,
            env={**os.environ, "DATABASE_URL": test_url.render_as_string(hide_password=False)},
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if migration.returncode != 0:
            pytest.fail(f"اجرای مایگریشن‌ها روی دیتابیس تست ناموفق بود:\n{migration.stderr[-3000:]}")

        yield test_url.render_as_string(hide_password=False)
    finally:
        asyncio.run(_run_on_maintenance_db(server_url, f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE)'))


# ---------------------------------------------------------------------------
# Session هر تست: داخل یک تراکنش که در پایان Rollback می‌شود
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db_session(test_database_url: str):
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        outer_transaction = await connection.begin()
        # commit/rollback های داخل API فقط روی یک SAVEPOINT اعمال می‌شوند، نه تراکنش بیرونی
        session = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer_transaction.rollback()  # Teardown: حذف تمام داده‌های این تست
    await engine.dispose()


class FakeCache:
    """جایگزین حافظه‌ای لایه‌ی کش Redis (app/core/cache.py) برای تست‌ها."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ttl_seconds: int) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def fake_cache() -> FakeCache:
    return FakeCache()


@pytest.fixture
def enqueued_tasks() -> list[tuple]:
    """هر کاری که API به صف پس‌زمینه بفرستد اینجا ثبت می‌شود (به‌جای Redis واقعی)."""
    return []


@pytest_asyncio.fixture
async def client(db_session, fake_cache, enqueued_tasks, monkeypatch, tmp_path):
    async def override_get_db():
        yield db_session

    async def fake_enqueue(func, *args, **kwargs):
        enqueued_tasks.append((func.__name__, args))
        return "test-job-id"

    async def noop_async(*args, **kwargs):
        return None

    app.dependency_overrides[get_db] = override_get_db

    # کش نشست کاربر و OTP بازیابی رمز → حافظه‌ی موقت همین تست
    monkeypatch.setattr(deps, "get_cached_json", fake_cache.get)
    monkeypatch.setattr(deps, "set_cached_json", fake_cache.set)
    monkeypatch.setattr(auth_router, "get_cached_json", fake_cache.get)
    monkeypatch.setattr(auth_router, "set_cached_json", fake_cache.set)
    monkeypatch.setattr(auth_router, "delete_cached", fake_cache.delete)

    # صف پس‌زمینه و ایمیل‌ها → فقط ثبت در لیست، بدون Redis
    monkeypatch.setattr(auth_router, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(auth_router, "notify_new_user_registered", noop_async)
    monkeypatch.setattr(resumes_router, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(applications_router, "trigger_status_change_email", noop_async)
    monkeypatch.setattr(interviews_router, "schedule_interview_reminder", lambda **kwargs: [])
    monkeypatch.setattr(interviews_router, "cancel_interview_reminder", lambda job_ids: None)

    # فایل‌های آپلودی در یک پوشه‌ی موقت (pytest خودش پاکش می‌کند)
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    local_storage = LocalStorageBackend()
    monkeypatch.setattr(resumes_router, "get_storage_backend", lambda: local_storage)

    # Rate Limit (۵ درخواست در دقیقه روی auth) در تست‌ها مانع نشود
    monkeypatch.setattr(limiter, "enabled", False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# ساخت کاربر و هدر احراز هویت
# ---------------------------------------------------------------------------
@pytest.fixture
def make_user(db_session):
    async def _make_user(role: str = "Candidate", email: str | None = None, is_active: bool = True) -> User:
        user = User(
            email=email or f"{role.lower()}-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password(TEST_PASSWORD),
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        # commit (نه فقط flush): داده‌ی آماده‌سازی تست از SAVEPOINT جاری بیرون می‌آید تا اگر خودِ
        # API در ادامه rollback کرد (مثلاً روی یک درخواست نامعتبر)، این داده‌ها از بین نروند.
        # همچنان داخل تراکنش بیرونی تست است و در Teardown پاک می‌شود.
        await db_session.commit()
        return user

    return _make_user


def auth_headers(user: User) -> dict[str, str]:
    access_token, _ = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def make_application(db_session, make_user):
    """
    یک «درخواست» کامل و آماده برای تست می‌سازد: آگهی (ساخته‌شده توسط یک HR) + کاربر Candidate
    و پروفایلش + ردیف applications با وضعیت دلخواه. خروجی: (application, candidate_user, job)
    """

    async def _make_application(status: str = "Draft", score_ai: int | None = None, job: Job | None = None):
        if job is None:
            creator = await make_user(role="HR_Manager")
            job = Job(title="Backend Developer", skills_required=["Python"], created_by=creator.id)
            db_session.add(job)
        candidate_user = await make_user(role="Candidate")
        candidate = Candidate(user_id=candidate_user.id, first_name="Sara", last_name="Ahmadi")
        db_session.add(candidate)
        await db_session.flush()

        application = Application(job_id=job.id, candidate_id=candidate.id, current_status=status, score_ai=score_ai)
        db_session.add(application)
        await db_session.commit()  # همان دلیل make_user
        return application, candidate_user, job

    return _make_application
