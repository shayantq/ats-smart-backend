"""
تست مایگریشن رمزنگاری (b8e4d2f1a9c6) روی دیتابیس جدا با داده‌ی قدیمیِ رمزنشده:

- upgrade: نام/تلفن/آدرس کارجو و متن خام/داده‌ی استخراج‌شده‌ی رزومه رمز می‌شوند، ایندکس کور جستجو ساخته و ایندکس
  تمام‌متن روی raw_text حذف می‌شود؛ برنامه همان مقادیر را باز می‌کند.
- downgrade: داده دقیقاً به متن قبلی و ساختار و ایندکس قبلی برمی‌گردد؛ upgrade دوباره هم بی‌خطر است.
"""

import asyncio
import json
import os
import sys
import uuid

import asyncpg

from app.core.crypto import FERNET_PREFIX, blind_index_token, decrypt_text
from tests.integration.conftest import PROJECT_ROOT
from tests.integration.test_tenancy_migration import legacy_database  # noqa: F401

PREVIOUS_REVISION = "d2f6b8a41c37"
PARSED = {"personal_info": {"name": "Reza Karimi", "phone": "09351112233"}, "skills": ["Go"]}


async def _alembic(database_url: str, *command: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *command,
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": database_url, "PYTHONIOENCODING": "utf-8"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    return process.returncode, output.decode("utf-8", errors="replace")


async def _row(connection: asyncpg.Connection, ids: dict) -> dict:
    candidate = await connection.fetchrow(
        "SELECT first_name, last_name, phone, location FROM candidates WHERE id = $1", ids["candidate"]
    )
    resume = await connection.fetchrow(
        "SELECT raw_text, parsed_data::text AS parsed FROM resumes WHERE id = $1", ids["resume"]
    )
    return {**dict(candidate), **dict(resume)}


async def _indexes(connection: asyncpg.Connection) -> set[str]:
    rows = await connection.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'resumes'")
    return {row["indexname"] for row in rows}


async def test_migration_encrypts_legacy_pii_and_downgrade_restores_it(legacy_database):  # noqa: F811
    url = legacy_database.render_as_string(hide_password=False)
    code, output = await _alembic(url, "upgrade", PREVIOUS_REVISION)
    assert code == 0, output[-3000:]

    connection = await asyncpg.connect(
        host=legacy_database.host,
        port=legacy_database.port or 5432,
        user=legacy_database.username,
        password=legacy_database.password,
        database=legacy_database.database,
    )
    try:
        ids = {name: uuid.uuid4() for name in ("owner", "company", "user", "candidate", "resume")}
        await connection.execute(
            "INSERT INTO users (id, email, password_hash, role, is_active) VALUES "
            "($1, 'owner@legacy.test', '!', 'Admin', true), ($2, 'reza@legacy.test', '!', 'Candidate', true)",
            ids["owner"],
            ids["user"],
        )
        await connection.execute(
            "INSERT INTO companies (id, name, owner_id) VALUES ($1, 'Legacy Org', $2)", ids["company"], ids["owner"]
        )
        await connection.execute(
            "INSERT INTO candidates (id, user_id, first_name, last_name, phone, location) "
            "VALUES ($1, $2, 'Reza', 'Karimi', '09351112233', 'Shiraz')",
            ids["candidate"],
            ids["user"],
        )
        await connection.execute(
            "INSERT INTO resumes (id, candidate_id, tenant_id, file_url, raw_text, parsed_data) "
            "VALUES ($1, $2, $3, 'legacy.pdf', 'Golang and Kafka engineer', $4::jsonb)",
            ids["resume"],
            ids["candidate"],
            ids["company"],
            json.dumps(PARSED),
        )
        plaintext = await _row(connection, ids)

        code, output = await _alembic(url, "upgrade", "head")
        assert code == 0, output[-3000:]
        encrypted = await _row(connection, ids)
        for column, value in encrypted.items():
            assert value.startswith(FERNET_PREFIX), column
        assert decrypt_text(encrypted["phone"]) == "09351112233"
        assert json.loads(decrypt_text(encrypted["parsed"])) == PARSED
        tokens = await connection.fetchval("SELECT search_tokens FROM resumes WHERE id = $1", ids["resume"])
        assert blind_index_token("kafka") in tokens and blind_index_token("golang") in tokens
        indexes = await _indexes(connection)
        assert "ix_resumes_search_tokens_gin" in indexes and "ix_resumes_raw_text_fts_v2" not in indexes

        code, output = await _alembic(url, "downgrade", PREVIOUS_REVISION)
        assert code == 0, output[-3000:]
        restored = await _row(connection, ids)
        assert {key: value for key, value in restored.items() if key != "parsed"} == {
            key: value for key, value in plaintext.items() if key != "parsed"
        }
        assert json.loads(restored["parsed"]) == PARSED
        indexes = await _indexes(connection)
        assert "ix_resumes_raw_text_fts_v2" in indexes and "ix_resumes_search_tokens_gin" not in indexes

        code, output = await _alembic(url, "upgrade", "head")  # دوباره: بدون رمزنگاری دوباره‌ی داده
        assert code == 0, output[-3000:]
        assert decrypt_text((await _row(connection, ids))["location"]) == "Shiraz"
    finally:
        await connection.close()
