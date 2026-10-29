"""حریم خصوصی: رمزنگاری داده‌های شخصی کارجو، ایندکس کور جستجوی رزومه، رضایت‌نامه و ناشناس‌سازی

Revision ID: b8e4d2f1a9c6
Revises: d2f6b8a41c37

- candidates.first_name/last_name/phone/location و resumes.raw_text/parsed_data → Text حاوی متن رمزشده‌ی
  Fernet (app/core/crypto.py). داده‌ی موجود دسته‌دسته در همین مایگریشن رمز می‌شود؛ مقداری که از قبل رمزشده
  است (gAAAAA…) دوباره رمز نمی‌شود، پس اجرای دوباره بی‌خطر است.
- جستجوی تمام‌متن روی raw_text دیگر ممکن نیست: ایندکس to_tsvector حذف و ستون resumes.search_tokens
  (HMAC کلمات، text[]) با ایندکس GIN جایش را می‌گیرد.
- users.data_consent_at/data_consent_version (رضایت‌نامه‌ی ثبت‌نام) و users.anonymized_at (حق فراموش شدن).

کلید از همان متغیرهای محیطی برنامه خوانده می‌شود؛ بدون کلید این مایگریشن پیش از هر تغییری متوقف می‌شود. Downgrade داده را
باز می‌کند و ساختار و ایندکس جستجوی قبلی را برمی‌گرداند.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op
from app.core.crypto import blind_index_tokens, decrypt_text, encrypt_text, is_encrypted, validate_keys

revision: str = "b8e4d2f1a9c6"
down_revision: Union[str, None] = "d2f6b8a41c37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH_SIZE = 500
CANDIDATE_COLUMNS = {"first_name": 100, "last_name": 100, "phone": 20, "location": 100}
FTS_INDEX = "ix_resumes_raw_text_fts_v2"
FTS_EXPRESSION = "to_tsvector('simple', translate(coalesce(raw_text, ''), './+#@_-', '       '))"


def _batches(connection, query: str):
    """ردیف‌ها به ترتیب id و دسته‌های BATCH_SIZE تایی (حافظه‌ی مایگریشن با حجم جدول رشد نمی‌کند)."""
    last_id = None
    while True:
        condition = "" if last_id is None else "WHERE id > :last_id"
        rows = connection.execute(
            sa.text(f"{query} {condition} ORDER BY id LIMIT {BATCH_SIZE}"), {"last_id": last_id}
        ).all()
        if not rows:
            return
        yield rows
        last_id = rows[-1].id


def _encrypt(value: str | None) -> str | None:
    return value if value is None or is_encrypted(value) else encrypt_text(value)


def _decrypt(value: str | None) -> str | None:
    return value if value is None or not is_encrypted(value) else decrypt_text(value)


def upgrade() -> None:
    validate_keys()  # بدون کلید: توقف پیش از هر تغییری (هیچ داده‌ای رمزنشده یا با کلید نامعلوم نمی‌ماند)
    op.add_column("users", sa.Column("data_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("data_consent_version", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("resumes", sa.Column("search_tokens", ARRAY(sa.Text()), nullable=True))

    op.execute(f"DROP INDEX IF EXISTS {FTS_INDEX}")
    op.execute("DROP INDEX IF EXISTS ix_resumes_raw_text_fts")
    for column in CANDIDATE_COLUMNS:
        op.alter_column(
            "candidates", column, type_=sa.Text(), existing_nullable=column not in ("first_name", "last_name")
        )
    op.alter_column("resumes", "parsed_data", type_=sa.Text(), postgresql_using="parsed_data::text")

    connection = op.get_bind()
    columns = ", ".join(CANDIDATE_COLUMNS)
    assignments = ", ".join(f"{column} = :{column}" for column in CANDIDATE_COLUMNS)
    for rows in _batches(connection, f"SELECT id, {columns} FROM candidates"):
        connection.execute(
            sa.text(f"UPDATE candidates SET {assignments} WHERE id = :id"),
            [
                {"id": row.id, **{column: _encrypt(getattr(row, column)) for column in CANDIDATE_COLUMNS}}
                for row in rows
            ],
        )
    for rows in _batches(connection, "SELECT id, raw_text, parsed_data FROM resumes"):
        connection.execute(
            sa.text(
                "UPDATE resumes SET raw_text = :raw_text, parsed_data = :parsed_data, search_tokens = :tokens "
                "WHERE id = :id"
            ),
            [
                {
                    "id": row.id,
                    "raw_text": _encrypt(row.raw_text),
                    "parsed_data": _encrypt(row.parsed_data),
                    "tokens": blind_index_tokens(_decrypt(row.raw_text)),
                }
                for row in rows
            ],
        )

    op.create_index("ix_resumes_search_tokens_gin", "resumes", ["search_tokens"], postgresql_using="gin")


def downgrade() -> None:
    validate_keys()
    op.drop_index("ix_resumes_search_tokens_gin", table_name="resumes")

    connection = op.get_bind()
    columns = ", ".join(CANDIDATE_COLUMNS)
    assignments = ", ".join(f"{column} = :{column}" for column in CANDIDATE_COLUMNS)
    for rows in _batches(connection, f"SELECT id, {columns} FROM candidates"):
        connection.execute(
            sa.text(f"UPDATE candidates SET {assignments} WHERE id = :id"),
            [
                {"id": row.id, **{column: _decrypt(getattr(row, column)) for column in CANDIDATE_COLUMNS}}
                for row in rows
            ],
        )
    for rows in _batches(connection, "SELECT id, raw_text, parsed_data FROM resumes"):
        connection.execute(
            sa.text("UPDATE resumes SET raw_text = :raw_text, parsed_data = :parsed_data WHERE id = :id"),
            [
                {"id": row.id, "raw_text": _decrypt(row.raw_text), "parsed_data": _decrypt(row.parsed_data)}
                for row in rows
            ],
        )

    op.alter_column("resumes", "parsed_data", type_=JSONB(), postgresql_using="parsed_data::jsonb")
    for column, length in CANDIDATE_COLUMNS.items():
        op.alter_column(
            "candidates", column, type_=sa.String(length), existing_nullable=column not in ("first_name", "last_name")
        )
    op.execute(f"CREATE INDEX IF NOT EXISTS {FTS_INDEX} ON resumes USING gin ({FTS_EXPRESSION})")
    op.execute(f"ALTER INDEX {FTS_INDEX} SET (fastupdate = on, gin_pending_list_limit = 4096)")

    op.drop_column("resumes", "search_tokens")
    op.drop_column("users", "anonymized_at")
    op.drop_column("users", "data_consent_version")
    op.drop_column("users", "data_consent_at")
