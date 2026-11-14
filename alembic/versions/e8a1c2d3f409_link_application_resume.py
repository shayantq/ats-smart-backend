"""اتصال صریح درخواست به رزومه؛ بدون حدس نگاشت داده‌های تاریخی."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e8a1c2d3f409"
down_revision = "c4f1a8e2b7d9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("applications", sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_applications_resume_id", "applications", "resumes", ["resume_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_applications_resume_id", "applications", type_="foreignkey")
    op.drop_column("applications", "resume_id")
