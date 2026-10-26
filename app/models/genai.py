"""
جداول بانک سؤال مصاحبه‌ی تولیدشده با هوش مصنوعی مولد (بخش ۲ نقشه‌ی راه):

    InterviewQuestionSet   یک درخواست تولید (کارجو × آگهی): وضعیت، تنظیمات، ورودی ارسالی به مدل
                           (برای ممیزی و بازتولید)، مصرف توکن و زمان پاسخ
    InterviewQuestion      هر سؤال با کلید پاسخ، معیارهای ارزیابی، نشانه‌های خطر و سؤال‌های پیگیری؛
                           به‌علاوه‌ی بازبینی مصاحبه‌کننده (ویرایش، تأیید برای بانک سؤال، یادداشت)
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin


class InterviewQuestionSet(TenantMixin, Base):
    __tablename__ = "interview_question_sets"
    __table_args__ = (
        Index("ix_interview_question_sets_application_id_created_at", "application_id", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')", name="ck_interview_question_sets_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # pending → processing → completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="fa")
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False, default="mixed")
    focus_skills: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False, server_default="{}")

    # ممیزی و بازتولید: نسخه‌ی Prompt، شناسه‌ی مدل (از تنظیمات) و پروفایل ساخت‌یافته‌ی ارسال‌شده — بدون
    # اطلاعات شناسایی شخصی (نام/ایمیل/تلفن هرگز به مدل زبانی فرستاده نمی‌شود؛ app/genai/prompts.py)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_model: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    input_profile: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    focus_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    questions: Mapped[list["InterviewQuestion"]] = relationship(
        back_populates="question_set", cascade="all, delete-orphan", order_by="InterviewQuestion.position"
    )


class InterviewQuestion(TenantMixin, Base):
    __tablename__ = "interview_questions"
    __table_args__ = (
        Index("uq_interview_questions_set_position", "question_set_id", "position", unique=True),
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="ck_interview_questions_difficulty"),
        # بانک سؤال مشترک: جست‌وجوی سؤال‌های تأییدشده بر اساس مهارت (بدون حساسیت به حروف)
        Index(
            "ix_interview_questions_approved_skill",
            text("lower(skill)"),
            "difficulty",
            postgresql_where=text("is_approved"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_question_sets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    category: Mapped[str] = mapped_column(String(30), nullable=False)
    skill: Mapped[str] = mapped_column(String(100), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_points: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    red_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    follow_ups: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # بازبینی انسانی — هیچ سؤالی بدون تأیید مصاحبه‌کننده وارد بانک سؤال مشترک نمی‌شود
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    interviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    question_set: Mapped["InterviewQuestionSet"] = relationship(back_populates="questions")
