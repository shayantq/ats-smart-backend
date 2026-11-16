"""تقویت اتصال رزومهٔ رویداد و محدودکردن ویرایش گروه به نویسنده."""

from alembic import op

revision = "a61d3e947b21"
down_revision = "a61d3e947b20"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER POLICY dossier_insert ON dossier_review_events WITH CHECK ("
        "app_current_scope()='tenant' AND tenant_id=app_current_tenant() AND actor_id=app_current_user_id() "
        "AND EXISTS (SELECT 1 FROM applications a JOIN resumes r ON r.id=a.resume_id "
        "WHERE a.id=dossier_review_events.application_id AND a.tenant_id=dossier_review_events.tenant_id "
        "AND r.id=dossier_review_events.resume_id AND r.tenant_id=a.tenant_id AND r.candidate_id=a.candidate_id))"
    )
    op.execute(
        "ALTER POLICY dossier_update ON dossier_reanalysis_batches USING ("
        "app_current_scope()='tenant' AND tenant_id=app_current_tenant() AND actor_id=app_current_user_id())"
    )


def downgrade():
    op.execute(
        "ALTER POLICY dossier_insert ON dossier_review_events WITH CHECK ("
        "app_current_scope()='tenant' AND tenant_id=app_current_tenant() AND actor_id=app_current_user_id() "
        "AND EXISTS (SELECT 1 FROM applications a WHERE a.id=dossier_review_events.application_id "
        "AND a.tenant_id=dossier_review_events.tenant_id))"
    )
    op.execute(
        "ALTER POLICY dossier_update ON dossier_reanalysis_batches USING ("
        "app_current_scope()='tenant' AND tenant_id=app_current_tenant())"
    )
