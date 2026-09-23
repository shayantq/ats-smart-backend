"""add GIN fulltext index on resumes.raw_text and B-Tree indexes for cursor pagination / filters

Revision ID: 852de21930b5
Revises: 412f8ab0d4e6
Create Date: 2026-09-22 00:00:00.000000

این مایگریشن بخش «بهینه‌سازی پایگاه‌داده» تسک صفحه‌بندی هوشمند و ایندکس‌گذاری
صلب را پیاده می‌کند:

۱) یک ایندکس GIN روی to_tsvector(raw_text) جدول resumes برای جستجوی
   تمام‌متن سریع (Full-Text Search).
۲) چند ایندکس B-Tree (تکی و مرکب) روی ستون‌های پرکاربردِ فیلتر/JOIN و همچنین
   ستون‌های مرتب‌سازیِ صفحه‌بندی مبتنی بر نشانگر (Cursor Pagination) در
   app/core/pagination.py.

همه‌ی ایندکس‌ها با CONCURRENTLY ساخته می‌شوند تا در محیط Production روی
جدول‌های پر‌رفت‌وآمد، هیچ قفل نوشتنی (ACCESS EXCLUSIVE) طولانی‌مدتی ایجاد
نکنند؛ به همین دلیل هر ساخت/حذف ایندکس باید خارج از یک تراکنش اجرا شود
(op.get_context().autocommit_block())، چون CREATE/DROP INDEX CONCURRENTLY
در PostgreSQL اصلاً داخل یک تراکنش مجاز نیست.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "852de21930b5"
down_revision: Union[str, None] = "412f8ab0d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # -----------------------------------------------------------
        # ساب‌تسک ۱: ایندکس GIN روی resumes.raw_text برای جستجوی تمام‌متن
        # -----------------------------------------------------------
        # از پیکربندی 'simple' به‌جای 'english' استفاده شده چون رزومه‌ها
        # می‌توانند فارسی/انگلیسی/مخلوط باشند؛ 'simple' هیچ stemming یا
        # stopword زبان‌محوری اعمال نمی‌کند (فقط توکنایز ساده)، پس برای متن
        # چندزبانه/ناشناخته امن‌تر و قابل‌پیش‌بینی‌تر از یک دیکشنری زبان
        # خاص است. coalesce(raw_text, '') لازم است چون raw_text nullable
        # است (رزومه‌هایی که هنوز پردازش OCR/متنی‌شان کامل نشده).
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_raw_text_fts "
            "ON resumes USING gin (to_tsvector('simple', coalesce(raw_text, '')))"
        )

        # -----------------------------------------------------------
        # ساب‌تسک ۲: ایندکس‌های B-Tree روی ستون‌های پرکاربرد فیلتر/JOIN/ORDER BY
        # -----------------------------------------------------------

        # --- جدول resumes: FK پرمصرف که تا امروز اصلاً ایندکس نداشت ---
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_candidate_id ON resumes (candidate_id)")

        # --- جدول jobs ---
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_status ON jobs (status)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_department ON jobs (department)")
        # ایندکس مرکب برای صفحه‌بندی مبتنی بر نشانگر: پوشش‌دهنده‌ی
        # ORDER BY created_at DESC, id DESC در GET /api/v1/jobs/
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_created_at_id ON jobs (created_at, id)")

        # --- جدول applications ---
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_applications_current_status "
            "ON applications (current_status)"
        )
        # ایندکس مرکب: هم فیلتر job_id (بورد کانبان GET /api/v1/applications/)
        # و هم ترتیب صفحه‌بندی (updated_at, id) را در یک اسکن ایندکس واحد
        # پوشش می‌دهد — به‌جای یک ایندکس تکی job_id + یک sort جداگانه.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_applications_job_id_updated_at_id "
            "ON applications (job_id, updated_at, id)"
        )
        # ایندکس مرکب مشابه برای مسیرهای پورتال کارجو (رهگیر وضعیت /
        # صندوق پیشنهادها) که هر دو روی candidate_id فیلتر و با همین
        # ترتیب صفحه‌بندی می‌شوند.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_applications_candidate_id_updated_at_id "
            "ON applications (candidate_id, updated_at, id)"
        )

        # --- جدول interviews ---
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_interviews_application_id "
            "ON interviews (application_id)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_interviews_interviewer_id "
            "ON interviews (interviewer_id)"
        )
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_interviews_status ON interviews (status)")
        # ایندکس مرکب برای صفحه‌بندی (scheduled_at, id)؛ همچنین فیلتر
        # بازه‌ای «روز» در app/routers/interviews.py (که دیگر با
        # func.date(scheduled_at) نوشته نمی‌شود تا Sargable بماند و از
        # همین ایندکس به‌صورت Range Scan استفاده کند) را پوشش می‌دهد.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_interviews_scheduled_at_id "
            "ON interviews (scheduled_at, id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_interviews_scheduled_at_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_interviews_status")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_interviews_interviewer_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_interviews_application_id")

        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_applications_candidate_id_updated_at_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_applications_job_id_updated_at_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_applications_current_status")

        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_jobs_created_at_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_jobs_department")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_jobs_status")

        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_candidate_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_raw_text_fts")
