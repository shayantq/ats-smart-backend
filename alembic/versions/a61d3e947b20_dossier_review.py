"""ثبت مستقل بازبینی و نسخه‌های رمز‌شدهٔ تحلیل با سیاست سازمان و یادداشت خصوصی."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a61d3e947b20"
down_revision = "f19b3a47d682"
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("tenant_id", UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    ]


def application():
    return [
        sa.Column("application_id", UUID(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", UUID(), sa.ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False),
    ]


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "dossier_review_heads",
        sa.Column("application_id", UUID(), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "dossier_review_events",
        *common(),
        *application(),
        sa.Column("actor_id", UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("visibility", sa.String(12), nullable=False),
        sa.CheckConstraint("visibility IN ('team','private')", name="ck_review_visibility"),
    )
    op.create_table(
        "dossier_analysis_versions",
        *common(),
        *application(),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("application_id", "fingerprint", name="uq_dossier_version_fingerprint"),
    )
    op.create_table(
        "dossier_reanalysis_batches",
        *common(),
        sa.Column("actor_id", UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_id", UUID(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
    )
    tenant = "app_current_scope() = 'tenant' AND tenant_id = app_current_tenant()"
    for table in [
        "dossier_review_heads",
        "dossier_review_events",
        "dossier_analysis_versions",
        "dossier_reanalysis_batches",
    ]:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        own = tenant
        if table == "dossier_review_events":
            own += " AND (visibility = 'team' OR actor_id = app_current_user_id())"
        op.execute(f"CREATE POLICY dossier_read ON {table} FOR SELECT USING ({own})")
        op.execute(f"GRANT SELECT ON {table} TO ats_app")
        if table == "dossier_analysis_versions":
            op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM ats_app")
            continue
        exists = (
            f"EXISTS (SELECT 1 FROM applications a WHERE a.id = {table}.application_id AND a.tenant_id = {table}.tenant_id)"
            if table != "dossier_reanalysis_batches"
            else "EXISTS (SELECT 1 FROM jobs j WHERE j.id = dossier_reanalysis_batches.job_id AND j.tenant_id = dossier_reanalysis_batches.tenant_id)"
        )
        check = f"{tenant} AND {exists}"
        if table != "dossier_review_heads":
            check += " AND actor_id = app_current_user_id()"
        op.execute(f"CREATE POLICY dossier_insert ON {table} FOR INSERT WITH CHECK ({check})")
        op.execute(f"GRANT INSERT ON {table} TO ats_app")
        if table in {"dossier_review_heads", "dossier_reanalysis_batches"}:
            op.execute(f"CREATE POLICY dossier_update ON {table} FOR UPDATE USING ({tenant}) WITH CHECK ({check})")
            op.execute(f"GRANT UPDATE ON {table} TO ats_app")
        else:
            op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM ats_app")
    for table in ["dossier_review_events", "dossier_analysis_versions"]:
        op.create_index(f"ix_{table}_application_id", table, ["application_id"])


def downgrade():
    for table in [
        "dossier_reanalysis_batches",
        "dossier_analysis_versions",
        "dossier_review_events",
        "dossier_review_heads",
    ]:
        op.drop_table(table)
