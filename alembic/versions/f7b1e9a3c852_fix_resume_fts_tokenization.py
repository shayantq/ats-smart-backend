"""fix resume full-text search index to correctly tokenize compound tech terms (Node.js, C++, C#, ASP.NET, ...)

Revision ID: f7b1e9a3c852
Revises: a4d8f0c2b716
Create Date: 2026-09-23 12:00:00.000000

باگ کشف‌شده در تست دستی موتور جستجو: ایندکس GIN اولیه‌ی مایگریشن
852de21930b5 روی عبارت `to_tsvector('simple', coalesce(raw_text, ''))` ساخته
شده بود. پارسر پیش‌فرض متن پستگرس رشته‌هایی مثل "Node.js" یا "C++" را (طبق
الگوی «شبه‌میزبان»/«شبه‌فایل» کلمه.کلمه) یک توکن ترکیبی واحد می‌بیند، نه دو
کلمه‌ی جدا — یعنی جستجوی تک‌کلمه‌ای "Node" هرگز با رزومه‌ای که فقط "Node.js"
نوشته مطابقت پیدا نمی‌کرد (نتیجه: `GET /candidates/search/?q=React AND Node`
حتی روی داده‌ی واقعاً منطبق هم `items: []` برمی‌گرداند).

رفع باگ (بنگرید app/core/search_query.py::resume_fts_tsvector_expression):
پیش از to_tsvector، نویسه‌های پرکاربرد در نام فناوری‌ها (./+#@_-) با
translate() به فاصله تبدیل می‌شوند — "Node.js" همین حالا "Node js" توکنایز
می‌شود و هم با "Node" هم "js" مطابقت دارد.

این مایگریشن، ایندکس قدیمی (روی عبارت بدون translate) را حذف و ایندکس جدید
روی عبارت نرمال‌شده را می‌سازد — طبق همان الگوی CONCURRENTLY/autocommit_block
مایگریشن‌های قبلی.

⚠️ نکته‌ی مهم برای محیط‌هایی که از قبل داده دارند: چون خودِ ستون raw_text
تغییر نمی‌کند (فقط عبارت ایندکس)، نیازی به پردازش مجدد رزومه‌ها نیست؛ کافی
است `alembic upgrade head` اجرا شود.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7b1e9a3c852"
down_revision: Union[str, None] = "a4d8f0c2b716"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_EXPR = "to_tsvector('simple', coalesce(raw_text, ''))"
_NEW_EXPR = "to_tsvector('simple', translate(coalesce(raw_text, ''), './+#@_-', '       '))"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_raw_text_fts_v2 "
            f"ON resumes USING gin ({_NEW_EXPR})"
        )
        # ایندکس قدیمی دیگر با عبارت کوئری جستجو یکی نیست، پس هیچ‌وقت توسط
        # برنامه‌ریز پستگرس انتخاب نمی‌شود — نگه‌داشتنش فقط فضا/سربار نوشتن
        # اضافه می‌کند، پس حذف می‌شود.
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_raw_text_fts")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_resumes_raw_text_fts ON resumes USING gin ({_OLD_EXPR})"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_resumes_raw_text_fts_v2")
