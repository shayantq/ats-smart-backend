"""چندمستاجری: ستون tenant_id روی جدول‌های عملیاتی + ایزوله‌سازی Row-Level Security

Revision ID: d2f6b8a41c37
Revises: a7c3e91f0b42
Create Date: 2026-10-25 10:00:00.000000

بدون قفل طولانی جدول‌ها (قابل اجرا روی دیتابیس در حال سرویس):

    ۱. ADD COLUMN tenant_id بدون DEFAULT و NULL‌پذیر — فقط تغییر متادیتا، بدون بازنویسی جدول.
    ۲. پر کردن داده‌های قبلی (Backfill) در دسته‌های BATCH_SIZE تایی، هر دسته یک تراکنش کوتاه —
       فقط قفل سطر، نه جدول.
    ۳. کلید خارجی با NOT VALID و سپس VALIDATE (قفل SHARE UPDATE EXCLUSIVE؛ خواندن و نوشتن آزاد است).
    ۴. NOT NULL از راه CHECK (… IS NOT NULL) NOT VALID → VALIDATE → SET NOT NULL: پستگرس ۱۲+ با
       دیدن CHECK معتبر، جدول را برای SET NOT NULL دوباره اسکن نمی‌کند.
    ۵. ایندکس‌ها با CREATE INDEX CONCURRENTLY.
    ۶. هر دستوری که قفل ACCESS EXCLUSIVE کوتاه لازم دارد (ADD COLUMN، ENABLE RLS، CREATE POLICY، …)
       حداکثر LOCK_TIMEOUT منتظر قفل می‌ماند و اگر تراکنش طولانی دیگری جلویش بود، به‌جای صف‌کردن همه‌ی
       درخواست‌های بعدی پشت سر خودش، کنار می‌کشد و با فاصله‌ی افزایشی دوباره تلاش می‌کند.

کل مایگریشن در autocommit_block اجرا می‌شود (CONCURRENTLY داخل تراکنش مجاز نیست، و هر گام باید
قفلش را فوراً آزاد کند).

داده‌های پیشین: کارمندان (غیر کارجو) و همه‌ی رکوردهای عملیاتی به سازمان مالکشان (companies.owner_id)
یا در نبودش به «سازمان پیش‌فرض» منتقل می‌شوند؛ هیچ ردیفی حذف یا بی‌سازمان نمی‌ماند.

RLS: نقش ats_app (NOLOGIN، بدون BYPASSRLS) ساخته می‌شود و درخواست‌های API در هر تراکنش به آن سوئیچ
می‌کنند (app/core/tenancy.py). Worker ها و مایگریشن‌ها با نقش اصلی اتصال (مالک جدول‌ها) کار می‌کنند.
"""

import logging
import time
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d2f6b8a41c37"
down_revision: Union[str, None] = "a7c3e91f0b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

APP_ROLE = "ats_app"
LOCK_TIMEOUT = "3s"
MAX_LOCK_ATTEMPTS = 20
BATCH_SIZE = 5000
DEFAULT_TENANT_NAME = "سازمان پیش‌فرض (داده‌های پیشین)"

# جدول‌های عملیاتی با tenant_id اجباری — به ترتیب والد ← فرزند (برای Backfill)
TENANT_TABLES = (
    "jobs",
    "applications",
    "resumes",
    "interviews",
    "status_history",
    "interview_question_sets",
    "interview_questions",
)
# tenant_id اختیاری: کارمند (کارجو سازمان ندارد) و مهارت (خالی = مهارت استاندارد عمومی)
OPTIONAL_TENANT_TABLES = ("users", "skills")
RLS_TABLES = ("companies", "candidates", *TENANT_TABLES, "skills")


# ---------------------------------------------------------------------------
# ابزار اجرای امن
# ---------------------------------------------------------------------------
def _sqlstate(error: Exception) -> str | None:
    for candidate in (getattr(error, "orig", None), getattr(getattr(error, "orig", None), "__cause__", None)):
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if value:
                return value
    return None


def _sql(statement: str, **params) -> sa.engine.CursorResult:
    return op.get_bind().execute(sa.text(statement), params)


def _locking(statement: str) -> None:
    """دستوری که قفل کوتاه روی جدول می‌گیرد: حداکثر LOCK_TIMEOUT صبر، وگرنه عقب‌نشینی و تلاش دوباره."""
    for attempt in range(1, MAX_LOCK_ATTEMPTS + 1):
        try:
            op.get_bind().exec_driver_sql(statement)
            return
        except sa.exc.DBAPIError as error:
            if _sqlstate(error) != "55P03" or attempt == MAX_LOCK_ATTEMPTS:
                raise
            delay = min(0.2 * 2**attempt, 5.0)
            logger.warning(
                "قفل جدول آزاد نبود (lock_timeout، تلاش %d) — %.1f ثانیه بعد دوباره: %s", attempt, delay, statement[:90]
            )
            time.sleep(delay)


def _create_index_concurrently(name: str, definition: str) -> None:
    """CREATE INDEX CONCURRENTLY؛ ایندکس نیمه‌کاره (INVALID) از تلاش ناموفق قبلی اول حذف می‌شود."""
    invalid = _sql(
        "SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid WHERE c.relname = :name AND NOT i.indisvalid",
        name=name,
    ).first()
    # CONCURRENTLY باید منتظر تمام شدن تراکنش‌های قدیمی بماند؛ lock_timeout این انتظار را نیمه‌کاره نکند
    op.get_bind().exec_driver_sql("SET lock_timeout = 0")
    try:
        if invalid:
            op.get_bind().exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        op.get_bind().exec_driver_sql(f"CREATE {definition.replace('INDEX', f'INDEX CONCURRENTLY IF NOT EXISTS {name}', 1)}")
    finally:
        op.get_bind().exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")


def _drop_index_concurrently(name: str) -> None:
    op.get_bind().exec_driver_sql("SET lock_timeout = 0")
    try:
        op.get_bind().exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    finally:
        op.get_bind().exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")


def _backfill(table: str, source: str, **params) -> int:
    """
    source: SELECT id, tenant_id … فقط برای ردیف‌هایی که tenant_id شان هنوز خالی است و مقدار جدیدشان
    خالی نیست (تا حلقه حتماً تمام شود). هر دسته یک تراکنش کوتاه (autocommit).
    """
    total = 0
    while True:
        updated = _sql(
            f"UPDATE {table} AS target SET tenant_id = source.tenant_id "
            f"FROM ({source} LIMIT {BATCH_SIZE}) AS source WHERE target.id = source.id",
            **params,
        ).rowcount
        total += updated
        if updated == 0:
            return total


_default_tenant_id = None


def _default_tenant() -> str:
    """سازمان پیش‌فرض برای داده‌ی پیشینِ بی‌مالک — فقط اگر واقعاً لازم شود ساخته می‌شود."""
    global _default_tenant_id
    if _default_tenant_id is None:
        existing = _sql("SELECT id FROM companies WHERE name = :name ORDER BY id LIMIT 1", name=DEFAULT_TENANT_NAME).first()
        if existing:
            _default_tenant_id = str(existing[0])
        else:
            owner = _sql(
                "SELECT id FROM users ORDER BY (role = 'Admin') DESC, (role <> 'Candidate') DESC, created_at, id LIMIT 1"
            ).first()
            _default_tenant_id = str(
                _sql(
                    "INSERT INTO companies (id, name, owner_id) VALUES (gen_random_uuid(), :name, :owner) RETURNING id",
                    name=DEFAULT_TENANT_NAME,
                    owner=owner[0],
                ).scalar_one()
            )
            logger.info("سازمان پیش‌فرض برای داده‌های پیشین ساخته شد: %s", _default_tenant_id)
    return _default_tenant_id


def _backfill_orphans(table: str, where: str = "TRUE") -> None:
    remaining = _sql(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE tenant_id IS NULL AND {where})").scalar()
    if remaining:
        _backfill(
            table,
            f"SELECT id, CAST(:tenant AS uuid) AS tenant_id FROM {table} WHERE tenant_id IS NULL AND {where}",
            tenant=_default_tenant(),
        )


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------
def upgrade() -> None:
    global _default_tenant_id
    _default_tenant_id = None
    with op.get_context().autocommit_block():
        op.get_bind().exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        _create_app_role()
        _add_columns()
        _backfill_existing_rows()
        _enforce_constraints()
        _create_rls_functions()
        _grant_privileges()
        _create_policies()
        op.get_bind().exec_driver_sql("RESET lock_timeout")


def _create_app_role() -> None:
    op.get_bind().exec_driver_sql(
        f"""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
            IF NOT pg_has_role(current_user, '{APP_ROLE}', 'MEMBER') THEN
                EXECUTE format('GRANT {APP_ROLE} TO %I', current_user);
            END IF;
        END $$"""
    )


def _add_columns() -> None:
    for table in (*OPTIONAL_TENANT_TABLES, *TENANT_TABLES):
        _locking(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id uuid")


def _backfill_existing_rows() -> None:
    # کارمند ← سازمانی که مالکش است؛ بقیه‌ی کارمندان ← سازمان پیش‌فرض
    _backfill(
        "users",
        "SELECT u.id, (SELECT c.id FROM companies c WHERE c.owner_id = u.id ORDER BY c.id LIMIT 1) AS tenant_id "
        "FROM users u WHERE u.tenant_id IS NULL AND u.role <> 'Candidate' "
        "AND EXISTS (SELECT 1 FROM companies c WHERE c.owner_id = u.id)",
    )
    _backfill_orphans("users", "role <> 'Candidate'")

    # آگهی ← company_id خودش، وگرنه سازمان سازنده
    _backfill(
        "jobs",
        "SELECT j.id, COALESCE(j.company_id, u.tenant_id) AS tenant_id FROM jobs j JOIN users u ON u.id = j.created_by "
        "WHERE j.tenant_id IS NULL AND COALESCE(j.company_id, u.tenant_id) IS NOT NULL",
    )
    _backfill_orphans("jobs")

    _backfill(
        "applications",
        "SELECT a.id, j.tenant_id FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.tenant_id IS NULL AND j.tenant_id IS NOT NULL",
    )
    _backfill_orphans("applications")

    # رزومه به آگهی وصل نیست؛ همراه درخواست در یک تراکنش ساخته می‌شود ← سازمان قدیمی‌ترین درخواست کارجو
    _backfill(
        "resumes",
        "SELECT r.id, (SELECT a.tenant_id FROM applications a WHERE a.candidate_id = r.candidate_id "
        "ORDER BY a.created_at, a.id LIMIT 1) AS tenant_id FROM resumes r "
        "WHERE r.tenant_id IS NULL AND EXISTS (SELECT 1 FROM applications a WHERE a.candidate_id = r.candidate_id)",
    )
    _backfill_orphans("resumes")

    for table in ("interviews", "status_history", "interview_question_sets"):
        _backfill(
            table,
            f"SELECT x.id, a.tenant_id FROM {table} x JOIN applications a ON a.id = x.application_id "
            "WHERE x.tenant_id IS NULL",
        )
        _backfill_orphans(table)

    _backfill(
        "interview_questions",
        "SELECT q.id, s.tenant_id FROM interview_questions q JOIN interview_question_sets s ON s.id = q.question_set_id "
        "WHERE q.tenant_id IS NULL",
    )
    _backfill_orphans("interview_questions")
    # skills: ردیف‌های موجود همه «مهارت استاندارد عمومی»اند (tenant_id خالی می‌ماند)


def _enforce_constraints() -> None:
    for table in (*OPTIONAL_TENANT_TABLES, *TENANT_TABLES):
        constraint = f"fk_{table}_tenant_id"
        exists = _sql("SELECT 1 FROM pg_constraint WHERE conname = :name", name=constraint).first()
        if not exists:
            _locking(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} FOREIGN KEY (tenant_id) "
                "REFERENCES companies (id) NOT VALID"
            )
        _locking(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")

    for table in TENANT_TABLES:
        check = f"ck_{table}_tenant_id_not_null"
        _locking(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {check}")
        _locking(f"ALTER TABLE {table} ADD CONSTRAINT {check} CHECK (tenant_id IS NOT NULL) NOT VALID")
        _locking(f"ALTER TABLE {table} VALIDATE CONSTRAINT {check}")
        _locking(f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL")
        _locking(f"ALTER TABLE {table} DROP CONSTRAINT {check}")

    for table in (*OPTIONAL_TENANT_TABLES, *TENANT_TABLES):
        _create_index_concurrently(f"ix_{table}_tenant_id", f"INDEX ON {table} (tenant_id)")

    # مهارت: نام یکتا در هر دامنه (یک‌بار بین مهارت‌های استاندارد، یک‌بار در هر سازمان)
    _create_index_concurrently(
        "uq_skills_tenant_name",
        "UNIQUE INDEX ON skills (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name))",
    )
    _locking("ALTER TABLE skills DROP CONSTRAINT IF EXISTS skills_name_key")


def _create_rls_functions() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "CREATE OR REPLACE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql STABLE "
        "AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$"
    )
    bind.exec_driver_sql(
        "CREATE OR REPLACE FUNCTION app_current_scope() RETURNS text LANGUAGE sql STABLE "
        "AS $$ SELECT COALESCE(NULLIF(current_setting('app.scope', true), ''), 'public') $$"
    )
    bind.exec_driver_sql(
        "CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS uuid LANGUAGE sql STABLE "
        "AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$"
    )
    # SECURITY DEFINER: پروفایل کارجوی جاری بدون گذر از RLS جدول candidates — مانع چرخه‌ی پالیسی‌ها
    # (پالیسی candidates به applications ارجاع می‌دهد و پالیسی applications به همین تابع)
    bind.exec_driver_sql(
        "CREATE OR REPLACE FUNCTION app_current_candidate_id() RETURNS uuid LANGUAGE sql STABLE "
        "SECURITY DEFINER SET search_path = public, pg_temp "
        "AS $$ SELECT c.id FROM candidates c WHERE app_current_scope() = 'candidate' "
        "AND c.user_id = app_current_user_id() $$"
    )


def _grant_privileges() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    _locking(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    _locking(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    bind.exec_driver_sql(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    # جدول‌های مایگریشن‌های بعدی هم خودکار در دسترس نقش درخواست‌ها باشند
    bind.exec_driver_sql(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    bind.exec_driver_sql(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}")


_TENANT_MATCH = "tenant_id = app_current_tenant()"
_OWN_CANDIDATE = "candidate_id = app_current_candidate_id()"
_JOB_TENANT = "tenant_id = (SELECT j.tenant_id FROM jobs j WHERE j.id = job_id)"

# (جدول، نام پالیسی، دستور، USING، WITH CHECK)
POLICIES = (
    # سازمان فقط ردیف خودش را می‌بیند/ویرایش می‌کند؛ ساخت سازمان فقط در حالت system (ثبت‌نام Admin)
    ("companies", "tenant_self_read", "SELECT", "id = app_current_tenant()", None),
    ("companies", "tenant_self_update", "UPDATE", "id = app_current_tenant()", "id = app_current_tenant()"),
    # کارجو: موجودیت سراسری. خودش پروفایلش را دارد؛ سازمان فقط متقاضیان خودش را می‌بیند
    (
        "candidates",
        "candidate_self",
        "ALL",
        "app_current_scope() = 'candidate' AND user_id = app_current_user_id()",
        "app_current_scope() = 'candidate' AND user_id = app_current_user_id()",
    ),
    (
        "candidates",
        "tenant_applicants_read",
        "SELECT",
        "EXISTS (SELECT 1 FROM applications a WHERE a.candidate_id = candidates.id "
        "AND a.tenant_id = app_current_tenant())",
        None,
    ),
    ("jobs", "tenant_isolation", "ALL", _TENANT_MATCH, _TENANT_MATCH),
    # آگهی شغلی عمومی است: بازدیدکننده‌ی ناشناس و کارجو همه‌ی آگهی‌ها را می‌بینند (فقط خواندن)
    ("jobs", "public_read", "SELECT", "app_current_scope() IN ('public', 'candidate')", None),
    ("applications", "tenant_isolation", "ALL", _TENANT_MATCH, _TENANT_MATCH),
    ("applications", "candidate_read", "SELECT", _OWN_CANDIDATE, None),
    ("applications", "candidate_apply", "INSERT", None, f"{_OWN_CANDIDATE} AND {_JOB_TENANT}"),
    ("applications", "candidate_respond", "UPDATE", _OWN_CANDIDATE, f"{_OWN_CANDIDATE} AND {_JOB_TENANT}"),
    ("resumes", "tenant_isolation", "ALL", _TENANT_MATCH, _TENANT_MATCH),
    ("resumes", "candidate_read", "SELECT", _OWN_CANDIDATE, None),
    (
        "resumes",
        "candidate_upload",
        "INSERT",
        None,
        f"{_OWN_CANDIDATE} AND EXISTS (SELECT 1 FROM jobs j WHERE j.tenant_id = resumes.tenant_id)",
    ),
    ("interviews", "tenant_isolation", "ALL", _TENANT_MATCH, _TENANT_MATCH),
    ("status_history", "tenant_isolation", "ALL", _TENANT_MATCH, _TENANT_MATCH),
    (
        "status_history",
        "candidate_read",
        "SELECT",
        "EXISTS (SELECT 1 FROM applications a WHERE a.id = application_id "
        "AND a.candidate_id = app_current_candidate_id())",
        None,
    ),
    (
        "status_history",
        "candidate_insert",
        "INSERT",
        None,
        "EXISTS (SELECT 1 FROM applications a WHERE a.id = application_id "
        "AND a.candidate_id = app_current_candidate_id() AND a.tenant_id = status_history.tenant_id)",
    ),
    ("interview_question_sets", "tenant_isolation", "ALL", _TENANT_MATCH, _TENANT_MATCH),
    ("interview_questions", "tenant_isolation", "ALL", _TENANT_MATCH, _TENANT_MATCH),
    # مهارت استاندارد (بدون سازمان) برای همه خواندنی؛ مهارت سفارشی فقط برای سازمان خودش
    ("skills", "shared_read", "SELECT", "tenant_id IS NULL OR tenant_id = app_current_tenant()", None),
    ("skills", "tenant_custom", "ALL", _TENANT_MATCH, _TENANT_MATCH),
)


def _create_policies() -> None:
    for table, name, command, using, check in POLICIES:
        clauses = f" USING ({using})" if using else ""
        clauses += f" WITH CHECK ({check})" if check else ""
        _locking(f"DROP POLICY IF EXISTS {name} ON {table}")
        _locking(f"CREATE POLICY {name} ON {table} FOR {command}{clauses}")
    # پالیسی‌ها پیش از فعال‌سازی ساخته می‌شوند. مالک جدول (نقش مایگریشن/Worker) طبق تعریف پستگرس از
    # RLS معاف است؛ نقش درخواست‌های API (ats_app) نیست.
    for table in RLS_TABLES:
        _locking(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------
def downgrade() -> None:
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        bind.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        for table in RLS_TABLES:
            _locking(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        for table, name, *_ in POLICIES:
            _locking(f"DROP POLICY IF EXISTS {name} ON {table}")
        for function in ("app_current_candidate_id", "app_current_user_id", "app_current_scope", "app_current_tenant"):
            bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {function}()")

        bind.exec_driver_sql(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
        )
        bind.exec_driver_sql(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}")
        _locking(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
        bind.exec_driver_sql(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
        bind.exec_driver_sql(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
        # خودِ نقش ats_app حذف نمی‌شود: نقش‌ها در سطح کل سرور پستگرس‌اند و دیتابیس‌های دیگر (مثلاً
        # دیتابیس‌های موقت تست) ممکن است هنوز از آن استفاده کنند.

        _drop_index_concurrently("uq_skills_tenant_name")
        _locking("ALTER TABLE skills ADD CONSTRAINT skills_name_key UNIQUE (name)")
        for table in (*OPTIONAL_TENANT_TABLES, *TENANT_TABLES):
            _drop_index_concurrently(f"ix_{table}_tenant_id")
            _locking(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id")
        bind.exec_driver_sql("RESET lock_timeout")
