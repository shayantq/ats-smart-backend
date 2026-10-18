"""ایندکس‌های GIN مهارت و سابقه برای جستجوی کارجویان در حجم بالای رزومه

Revision ID: 9c4e2a7b1d35
Revises: b5e2c9d4a710
Create Date: 2026-10-19 10:00:00.000000

مشکل: فیلتر مهارت جستجوی کارجویان (app/routers/candidates.py) با
`jsonb_array_elements_text(skill_analysis -> 'skills')` + `lower()` روی هر ردیف کار می‌کرد؛ چنین
شرطی هیچ ایندکسی را به کار نمی‌گیرد و با هر جستجو کل جدول resumes خوانده می‌شد. ایندکس GIN قبلی
(`ix_resumes_skill_analysis_gin`، jsonb_path_ops) فقط عملگر @> روی خودِ JSON را پوشش می‌داد که هیچ
کوئری‌ای از آن استفاده نمی‌کرد — فقط سربار نوشتن هر رزومه‌ی جدید بود.

راه‌حل:
  ۱. تابع IMMUTABLE «ats_resume_skill_keys»: فهرست یکتا و حروف‌کوچک مهارت‌های هر رزومه (text[])
     — حساسیت به حروف بزرگ/کوچک مثل قبل حذف می‌شود («django» = «Django»)
  ۲. ایندکس GIN روی همین آرایه (عملگر @> آرایه): «کارجویان دارای مهارت X» = Bitmap Index Scan
     به‌جای Seq Scan؛ با fastupdate (فهرست انتظار) تا درج انبوه رزومه‌ها کند نشود
  ۳. ایندکس B-Tree روی سابقه‌ی خالص (تابع IMMUTABLE «ats_resume_experience_years») برای min_experience_years
  ۴. Autovacuum حساس به درج برای resumes: فهرست انتظار GIN مرتب در ایندکس اصلی ادغام و آمار
     برنامه‌ریز پستگرس با ورود حجم بالای رزومه به‌روز می‌ماند
  ۵. حذف ایندکس بلااستفاده‌ی ix_resumes_skill_analysis_gin

همه‌ی ایندکس‌ها CONCURRENTLY ساخته/حذف می‌شوند (بدون قفل نوشتن روی جدول در Production)؛ نسخه‌ی
قبلی کد همچنان کار می‌کند (Expand/Contract — فقط ایندکس و تابع اضافه می‌شود).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "9c4e2a7b1d35"
down_revision: Union[str, None] = "b5e2c9d4a710"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# CASE روی jsonb_typeof: ساختار نامعتبر (مثلاً skills غیرآرایه) هرگز درج رزومه یا ساخت ایندکس را خراب نمی‌کند
_SKILL_KEYS_FUNCTION = """
CREATE OR REPLACE FUNCTION ats_resume_skill_keys(analysis jsonb) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(DISTINCT lower(skill)), '{}'::text[])
    FROM jsonb_array_elements_text(
        CASE jsonb_typeof(analysis -> 'skills') WHEN 'array' THEN analysis -> 'skills' ELSE '[]'::jsonb END
    ) AS skill
$$
"""

_EXPERIENCE_FUNCTION = """
CREATE OR REPLACE FUNCTION ats_resume_experience_years(analysis jsonb) RETURNS double precision
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE jsonb_typeof(analysis -> 'total_experience_years')
        WHEN 'number' THEN (analysis ->> 'total_experience_years')::double precision
    END
$$
"""


def upgrade() -> None:
    op.execute(_SKILL_KEYS_FUNCTION)
    op.execute(_EXPERIENCE_FUNCTION)
    # درج‌محور: پس از هر ۵٪ (حداقل ۵۰۰) رزومه‌ی جدید، VACUUM/ANALYZE خودکار — پیش‌فرض پستگرس ۲۰٪ است
    op.execute(
        "ALTER TABLE resumes SET ("
        "autovacuum_vacuum_insert_scale_factor = 0.05, autovacuum_vacuum_insert_threshold = 500, "
        "autovacuum_analyze_scale_factor = 0.05, autovacuum_analyze_threshold = 500)"
    )
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_skill_keys_gin "
            "ON resumes USING gin (ats_resume_skill_keys(skill_analysis)) "
            "WITH (fastupdate = on, gin_pending_list_limit = 4096)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_experience_years "
            "ON resumes (ats_resume_experience_years(skill_analysis))"
        )
        # فهرست انتظار ایندکس تمام‌متن رزومه‌ها هم صریحاً مثل ایندکس مهارت (۴ مگابایت، با fastupdate)
        op.execute("ALTER INDEX IF EXISTS ix_resumes_raw_text_fts_v2 SET (fastupdate = on, gin_pending_list_limit = 4096)")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_skill_analysis_gin")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_skill_analysis_gin "
            "ON resumes USING gin (skill_analysis jsonb_path_ops)"
        )
        op.execute("ALTER INDEX IF EXISTS ix_resumes_raw_text_fts_v2 RESET (fastupdate, gin_pending_list_limit)")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_experience_years")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_skill_keys_gin")
    op.execute(
        "ALTER TABLE resumes RESET (autovacuum_vacuum_insert_scale_factor, autovacuum_vacuum_insert_threshold, "
        "autovacuum_analyze_scale_factor, autovacuum_analyze_threshold)"
    )
    op.execute("DROP FUNCTION IF EXISTS ats_resume_experience_years(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS ats_resume_skill_keys(jsonb)")
