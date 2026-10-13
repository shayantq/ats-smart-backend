"""add created_at to applications (needed for the analytics time-series endpoint)

Revision ID: c39a7f1de204
Revises: f7b1e9a3c852
Create Date: 2026-09-24 00:00:00.000000

جدول applications تا پیش از این فقط updated_at داشت (که با هر تغییر وضعیت
روی بورد کانبان بازنویسی می‌شود) و هیچ ستونی برای «زمان واقعی ثبت درخواست»
نداشت. این نبود دقیقاً همان چیزی‌ست که ساب‌تسک «تولید داده‌های سری زمانی
(روند ثبت درخواست‌های استخدام در ۳۰ روز گذشته)» در app/routers/analytics.py
به آن نیاز دارد — بدون created_at، اصلاً امکان محاسبه‌ی این متریک وجود
نداشت.

Backfill رکوردهای موجود: چون خودِ applications چیزی درباره‌ی زمان ثبت
اولیه‌شان ندارد، بهترین تخمین موجود، اولین ردیف status_history مربوط به هر
درخواست است (یعنی اولین باری که HR واقعاً وضعیتش را تغییر داده) — و اگر
حتی آن هم وجود نداشت (هنوز در Draft مانده و هیچ تغییری نخورده)، از
updated_at و در نهایت از NOW() استفاده می‌شود. این فقط یک تخمین برای
داده‌ی تاریخیِ از قبل موجود است؛ از این مایگریشن به بعد، created_at با
server_default = NOW() دقیقاً و به‌صورت خودکار در لحظه‌ی ثبت واقعی پر
می‌شود.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c39a7f1de204"
down_revision: Union[str, None] = "f7b1e9a3c852"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE applications a
        SET created_at = COALESCE(
            (SELECT MIN(sh.changed_at) FROM status_history sh WHERE sh.application_id = a.id),
            a.updated_at,
            NOW()
        )
        WHERE a.created_at IS NULL
        """
    )

    op.alter_column("applications", "created_at", server_default=sa.text("now()"), nullable=False)

    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_applications_created_at ON applications (created_at)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_applications_created_at")

    op.drop_column("applications", "created_at")
