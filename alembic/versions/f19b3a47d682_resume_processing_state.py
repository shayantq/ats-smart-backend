"""ثبت مستقل وضعیت پردازش رزومه، بدون تغییر وضعیت استخدام."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f19b3a47d682"
down_revision = "e8a1c2d3f409"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("resumes", sa.Column("processing_state", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("resumes", "processing_state")
