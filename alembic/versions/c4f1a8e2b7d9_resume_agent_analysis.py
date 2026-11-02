"""اکوسیستم چندعاملی پردازش رزومه: ستون رمزشده‌ی resumes.agent_analysis

Revision ID: c4f1a8e2b7d9
Revises: b8e4d2f1a9c6

خروجی یکپارچه‌ی عامل ناظر (JSON رمزشده‌ی Fernet — app/core/crypto.py::EncryptedJSON). فقط افزودن یک ستون
nullable: هیچ داده‌ای تغییر نمی‌کند، قفل طولانی ندارد و با نسخه‌ی قبلی کد سازگار است (Expand). رزومه‌های قبلی
خالی می‌مانند تا دوباره پردازش شوند.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c4f1a8e2b7d9"
down_revision: Union[str, None] = "b8e4d2f1a9c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("agent_analysis", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "agent_analysis")
