"""add supporting indexes for the advanced candidate search engine (skills/experience/ai score filters)

Revision ID: a4d8f0c2b716
Revises: 852de21930b5
Create Date: 2026-09-23 00:00:00.000000

این مایگریشن ایندکس‌های پشتیبان موتور جستجوی پیشرفته‌ی کارجویان
(GET /api/v1/candidates/search/) را اضافه می‌کند — جستجوی تمام‌متن روی
raw_text از قبل توسط ایندکس GIN مایگریشن 852de21930b5 پوشش داده شده؛ این
مایگریشن مکمل آن است، برای سه فیلتر ساختاریافته‌ی دیگر:

۱) ایندکس GIN روی ستون JSONB جدول resumes (`skill_analysis`) با
   jsonb_path_ops — برای سریع‌تر شدن EXISTS(... skill_analysis -> 'skills' ...)
   و مقایسه‌ی total_experience_years در فیلترهای skills/min_experience_years.
۲) ایندکس مرکب (candidate_id, score_ai) روی applications — برای سریع‌تر شدن
   EXISTS(... candidate_id = ... AND score_ai >= ...) در فیلتر min_ai_score؛
   ایندکس مرکب موجود (candidate_id, updated_at, id) چون score_ai ستون دومش
   نیست برای این فیلتر خاص کارآمد نبود.

مثل مایگریشن قبلی، همه‌ی ایندکس‌ها با CONCURRENTLY (خارج از تراکنش، طبق
op.get_context().autocommit_block()) ساخته می‌شوند تا هیچ قفل نوشتنی
طولانی‌مدتی روی جدول‌های پرترافیک ایجاد نشود.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d8f0c2b716"
down_revision: Union[str, None] = "852de21930b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # jsonb_path_ops سبک‌تر و سریع‌تر از GIN پیش‌فرض است، چون فقط عملگرهای
        # containment (@>) را پشتیبانی می‌کند — دقیقاً همان چیزی که فیلترهای
        # این موتور جستجو (وجود یک مهارت خاص یا یک کلید JSON خاص) نیاز دارند.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_skill_analysis_gin "
            "ON resumes USING gin (skill_analysis jsonb_path_ops)"
        )

        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_applications_candidate_id_score_ai "
            "ON applications (candidate_id, score_ai)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_applications_candidate_id_score_ai")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_skill_analysis_gin")
