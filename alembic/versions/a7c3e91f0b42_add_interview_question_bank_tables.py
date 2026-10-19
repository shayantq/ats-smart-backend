"""جداول بانک سؤال مصاحبه‌ی تولیدشده با هوش مصنوعی مولد

Revision ID: a7c3e91f0b42
Revises: 9c4e2a7b1d35
Create Date: 2026-10-19 12:00:00.000000

interview_question_sets: هر درخواست تولید سؤال برای یک application (کارجو × آگهی) — وضعیت، تنظیمات،
پروفایل ارسالی به مدل (ممیزی)، مصرف توکن و زمان پاسخ.
interview_questions: سؤال‌ها با کلید پاسخ و بازبینی مصاحبه‌کننده؛ ایندکس جزئی روی سؤال‌های تأییدشده
برای جست‌وجوی بانک سؤال مشترک بر اساس مهارت.

فقط جدول جدید (Expand) — نسخه‌ی قبلی کد بدون تغییر کار می‌کند.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7c3e91f0b42"
down_revision: Union[str, None] = "9c4e2a7b1d35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_question_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("language", sa.String(5), nullable=False, server_default="fa"),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(10), nullable=False, server_default="mixed"),
        sa.Column("focus_skills", postgresql.ARRAY(sa.String(100)), nullable=False, server_default="{}"),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("provider_model", sa.String(150), nullable=True),
        sa.Column("input_profile", postgresql.JSONB(), nullable=True),
        sa.Column("focus_summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')", name="ck_interview_question_sets_status"
        ),
    )
    op.create_index(
        "ix_interview_question_sets_application_id_created_at",
        "interview_question_sets",
        ["application_id", "created_at"],
    )

    op.create_table(
        "interview_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_question_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("skill", sa.String(100), nullable=False),
        sa.Column("difficulty", sa.String(10), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=False),
        sa.Column("evaluation_points", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("red_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("follow_ups", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interviewer_notes", sa.Text(), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="ck_interview_questions_difficulty"),
    )
    op.create_index(
        "uq_interview_questions_set_position", "interview_questions", ["question_set_id", "position"], unique=True
    )
    op.create_index(
        "ix_interview_questions_approved_skill",
        "interview_questions",
        [sa.text("lower(skill)"), "difficulty"],
        postgresql_where=sa.text("is_approved"),
    )


def downgrade() -> None:
    op.drop_index("ix_interview_questions_approved_skill", table_name="interview_questions")
    op.drop_index("uq_interview_questions_set_position", table_name="interview_questions")
    op.drop_table("interview_questions")
    op.drop_index("ix_interview_question_sets_application_id_created_at", table_name="interview_question_sets")
    op.drop_table("interview_question_sets")
