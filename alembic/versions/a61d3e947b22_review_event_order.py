"""ترتیب قطعی رویداد مستقل از تغییر ساعت یا زمان شروع تراکنش."""

from alembic import op
import sqlalchemy as sa

revision = "a61d3e947b22"
down_revision = "a61d3e947b21"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "dossier_review_events", sa.Column("sequence", sa.BigInteger(), sa.Identity(always=True), nullable=False)
    )
    op.create_unique_constraint("uq_dossier_review_sequence", "dossier_review_events", ["sequence"])


def downgrade():
    op.drop_constraint("uq_dossier_review_sequence", "dossier_review_events", type_="unique")
    op.drop_column("dossier_review_events", "sequence")
