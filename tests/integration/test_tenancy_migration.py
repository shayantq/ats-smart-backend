"""
تست مایگریشن چندمستاجری (d2f6b8a41c37) روی یک دیتابیس جدا با داده‌ی قدیمی (بدون tenant_id):

- داده‌ی پیشین حفظ می‌شود: هیچ ردیفی حذف یا بی‌سازمان نمی‌ماند؛ کارمندان و رکوردها به «سازمان پیش‌فرض»
  می‌روند، کارجو و مهارت استاندارد بی‌سازمان می‌مانند.
- بدون خطای قفل جدول: هم‌زمان با مایگریشن، یک تراکنش طولانی (شبیه ترافیک واقعی) قفل جدول jobs را نگه
  می‌دارد. مایگریشن به‌جای خطا یا مسدود کردن طولانی بقیه، با lock_timeout کوتاه عقب می‌کشد، دوباره تلاش
  می‌کند و موفق تمام می‌شود؛ خواندن‌های هم‌زمان هم حداکثر چند ثانیه منتظر می‌مانند.
"""

import asyncio
import os
import sys
import time
import uuid

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.integration.conftest import PROJECT_ROOT, _run_on_maintenance_db

PREVIOUS_REVISION = "a7c3e91f0b42"
BLOCKER_SECONDS = 7


async def _alembic(database_url: str, target: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        target,
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": database_url, "PYTHONIOENCODING": "utf-8"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    return process.returncode, output.decode("utf-8", errors="replace")


async def _connect(url) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=url.host, port=url.port or 5432, user=url.username, password=url.password, database=url.database
    )


async def _seed_legacy_data(connection: asyncpg.Connection) -> dict:
    ids = {
        name: uuid.uuid4() for name in ("admin", "hr", "cand_user", "job", "cand", "app", "resume", "interview", "qset")
    }
    await connection.execute(
        "INSERT INTO users (id, email, password_hash, role, is_active) VALUES "
        "($1, 'admin@legacy.test', '!', 'Admin', true), ($2, 'hr@legacy.test', '!', 'HR_Manager', true), "
        "($3, 'cand@legacy.test', '!', 'Candidate', true)",
        ids["admin"],
        ids["hr"],
        ids["cand_user"],
    )
    await connection.execute(
        "INSERT INTO jobs (id, title, status, created_by) VALUES ($1, 'Legacy job', 'Active', $2)",
        ids["job"],
        ids["hr"],
    )
    await connection.execute(
        "INSERT INTO candidates (id, user_id, first_name, last_name) VALUES ($1, $2, 'Old', 'Data')",
        ids["cand"],
        ids["cand_user"],
    )
    await connection.execute(
        "INSERT INTO applications (id, job_id, candidate_id, current_status) VALUES ($1, $2, $3, 'Screening')",
        ids["app"],
        ids["job"],
        ids["cand"],
    )
    await connection.execute(
        "INSERT INTO resumes (id, candidate_id, file_url) VALUES ($1, $2, 'legacy.pdf')", ids["resume"], ids["cand"]
    )
    await connection.execute(
        "INSERT INTO interviews (id, application_id, interviewer_id, status) VALUES ($1, $2, $3, 'Pending')",
        ids["interview"],
        ids["app"],
        ids["hr"],
    )
    await connection.execute(
        "INSERT INTO status_history (id, application_id, old_status, new_status, changed_by) "
        "VALUES (gen_random_uuid(), $1, 'Applied', 'Screening', $2)",
        ids["app"],
        ids["hr"],
    )
    await connection.execute(
        "INSERT INTO interview_question_sets (id, application_id, job_id, candidate_id, requested_by, status, "
        "language, question_count, difficulty, prompt_version) "
        "VALUES ($1, $2, $3, $4, $5, 'completed', 'fa', 1, 'mixed', 'v1')",
        ids["qset"],
        ids["app"],
        ids["job"],
        ids["cand"],
        ids["hr"],
    )
    await connection.execute(
        "INSERT INTO interview_questions (id, question_set_id, position, category, skill, difficulty, question, "
        "purpose, expected_answer, evaluation_points, red_flags, follow_ups, estimated_minutes, is_approved) "
        "VALUES (gen_random_uuid(), $1, 1, 'technical', 'Python', 'easy', 'q', 'p', 'a', '[]', '[]', '[]', 5, false)",
        ids["qset"],
    )
    await connection.execute("INSERT INTO skills (name) VALUES ('Python')")
    return ids


@pytest.fixture
def legacy_database(test_database_url):
    server_url = make_url(test_database_url)
    name = f"{server_url.database}_mig_{uuid.uuid4().hex[:6]}"
    asyncio.run(_run_on_maintenance_db(server_url, f'CREATE DATABASE "{name}"'))
    try:
        yield server_url.set(database=name)
    finally:
        asyncio.run(_run_on_maintenance_db(server_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


async def test_migration_preserves_legacy_data_and_survives_table_locks(legacy_database):
    url_string = legacy_database.render_as_string(hide_password=False)
    code, output = await _alembic(url_string, PREVIOUS_REVISION)
    assert code == 0, output[-3000:]

    connection = await _connect(legacy_database)
    blocker = await _connect(legacy_database)
    reader = await _connect(legacy_database)
    try:
        ids = await _seed_legacy_data(connection)
        tables = ("users", "jobs", "applications", "resumes", "interviews", "status_history", "interview_questions")
        counts_before = {table: await connection.fetchval(f"SELECT count(*) FROM {table}") for table in tables}

        # تراکنش طولانی که قفل ACCESS SHARE روی jobs نگه می‌دارد — ADD COLUMN روی jobs باید منتظرش بماند
        blocker_transaction = blocker.transaction()
        await blocker_transaction.start()
        await blocker.fetchval("SELECT count(*) FROM jobs")

        migration = asyncio.create_task(_alembic(url_string, "head"))
        read_latencies = []
        started = time.monotonic()
        while time.monotonic() - started < BLOCKER_SECONDS:
            began = time.monotonic()
            await reader.fetchval("SELECT count(*) FROM jobs")
            read_latencies.append(time.monotonic() - began)
            await asyncio.sleep(0.2)
        await blocker_transaction.commit()

        code, output = await migration
        assert code == 0, output[-3000:]
        assert "lock_timeout" in output  # قفل در دسترس نبود و مسیر «عقب‌نشینی و تلاش دوباره» واقعاً اجرا شد
        # هیچ خواندنی پشت ALTER منتظر قفل گیر نماند: حداکثر به اندازه‌ی lock_timeout (۳ ثانیه)
        assert max(read_latencies) < 4.5, read_latencies

        counts_after = {table: await connection.fetchval(f"SELECT count(*) FROM {table}") for table in tables}
        assert counts_after == counts_before  # هیچ داده‌ای از دست نرفت

        default_tenant = await connection.fetchrow("SELECT id, owner_id FROM companies")
        assert default_tenant["owner_id"] == ids["admin"]
        for table in ("jobs", "applications", "resumes", "interviews", "status_history", "interview_questions"):
            tenants = await connection.fetch(f"SELECT DISTINCT tenant_id FROM {table}")
            assert [row["tenant_id"] for row in tenants] == [default_tenant["id"]], table
            nullable = await connection.fetchval(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = 'tenant_id'",
                table,
            )
            assert nullable == "NO", table
        staff = await connection.fetch("SELECT role, tenant_id FROM users ORDER BY role")
        assert {(row["role"], row["tenant_id"]) for row in staff} == {
            ("Admin", default_tenant["id"]),
            ("HR_Manager", default_tenant["id"]),
            ("Candidate", None),
        }
        assert await connection.fetchval("SELECT tenant_id FROM skills") is None  # مهارت استاندارد عمومی

        invalid_indexes = await connection.fetchval(
            "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname LIKE 'ix_%_tenant_id' AND NOT i.indisvalid"
        )
        assert invalid_indexes == 0
        assert await connection.fetchval("SELECT relrowsecurity FROM pg_class WHERE relname = 'resumes'") is True
    finally:
        await asyncio.gather(connection.close(), blocker.close(), reader.close())
