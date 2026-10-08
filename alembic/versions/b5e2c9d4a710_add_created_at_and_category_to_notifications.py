"""add created_at and category to notifications (in-app ops alerts channel)

Revision ID: b5e2c9d4a710
Revises: c39a7f1de204
Create Date: 2026-10-08 00:00:00.000000

جدول notifications از ابتدا (مایگریشن اولیه) ساخته شده بود ولی تا پیش از
این هیچ‌جا استفاده نمی‌شد و ستون زمانی نداشت. حالا به‌عنوان «کانال پیام‌رسان
داخل سایت» برای تیم فنی استفاده می‌شود: هشدارهای Alertmanager و گزارش‌های
خط لوله‌ی CI/CD (بنگرید app/routers/ops.py) — که بدون created_at، نه
مرتب‌سازی «جدیدترین اول» ممکن بود و نه صفحه‌بندی مبتنی بر نشانگر.

Backfill: ردیف‌های احتمالی موجود زمان واقعی ندارند؛ NOW() تنها تخمین ممکن است.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e2c9d4a710"
down_revision: Union[str, None] = "c39a7f1de204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("category", sa.String(length=50), nullable=True))
    op.add_column(
        "notifications",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # پوشش هم‌زمان فیلتر user_id و ترتیب صفحه‌بندی (created_at DESC, id) در
    # مسیر GET /api/v1/notifications/me — همان الگوی ایندکس‌های مرکب applications
    op.create_index(
        "ix_notifications_user_id_created_at_id",
        "notifications",
        ["user_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_id_created_at_id", table_name="notifications")
    op.drop_column("notifications", "created_at")
    op.drop_column("notifications", "category")
