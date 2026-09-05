"""
جداول فرآیندی و مهارتی سیستم (Process and Skill Tables (ساب تسک دوم)): شامل جداولی که فرآیندهای اصلی سیستم را مدیریت می‌کنند و همچنین بانک اطلاعاتی مهارت‌های استاندارد بازار کار.
Applications, Interviews, Resumes, Skills
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Application(Base):
    """
    جدول درخواست‌ها: حلقه‌ی وصل کارجو به پوزیشن شغلی و بورد کانبان.

    current_status همیشه باید یکی از مقادیر ماشین وضعیت باشد (app/core/state_machine.py)
    و تغییرش فقط باید از طریق اندپوینت PUT /api/v1/applications/{id}/status انجام شود
    تا گاردریل‌های ضدپرش (Anti-Skipping) رعایت شوند.
    """

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    current_status: Mapped[str] = mapped_column(String(50), default="Draft", nullable=False)
    score_ai: Mapped[int] = mapped_column(Integer, nullable=True)
    # آخرین زمان تغییر وضعیت (سرور آن را در هر UPDATE موفق خودکار به‌روز می‌کند)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship()
    candidate: Mapped["Candidate"] = relationship()
    interviews: Mapped[list["Interview"]] = relationship(back_populates="application")
    status_history: Mapped[list["StatusHistory"]] = relationship(back_populates="application")


class Interview(Base):
    """جدول مصاحبه‌ها: تنظیمات و اطلاعات مربوط به جلسات ارزیابی."""

    __tablename__ = "interviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False
    )
    interviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # timezone=True عمداً اضافه شد (قبلاً نبود) تا با بقیه‌ی ستون‌های زمانی پروژه
    # (مثل updated_at) هم‌خوان باشد و مقایسه‌ی «۲۴ ساعت پیش از الان» بدون خطای
    # naive/aware ممکن شود (بنگرید app/core/interview_scheduler.py)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    meeting_link: Mapped[str] = mapped_column(String(500), nullable=True)
    # شناسه‌ی کارهای زمان‌بندی‌شده‌ی یادآور (rq-scheduler) برای این جلسه — تا در
    # صورت تغییر زمان یا لغو مصاحبه، بتوان یادآورهای قبلی را cancel کرد
    reminder_job_ids: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(100)), nullable=True)

    application: Mapped["Application"] = relationship(back_populates="interviews")
    interviewer: Mapped["User"] = relationship()


class Resume(Base):
    """جدول رزومه‌ها: مدیریت فایل‌های فیزیکی آپلود شده."""

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # فیلد متنی خام رزومه جهت فعال‌سازی موتور جستجوی متنی (Full-Text Search / GIN Index) در آینده
    raw_text: Mapped[str] = mapped_column(Text, nullable=True)
    # خروجی ساختاریافته‌ی ماژول NER (اطلاعات فردی + سوابق تحصیلی + تجربیات شغلی)
    # که به مرحله‌ی بعدی خط لوله‌ی هوش مصنوعی (امتیازدهی) منتقل می‌شود
    parsed_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # خروجی موتور مهارت (Skill Engine): مهارت‌های تطبیق‌یافته با گراف مهارت +
    # تحلیل خالص سال‌های سابقه‌ی کاری (بعد از کسر تداخل و فیلتر دوره‌های نامعتبر)
    skill_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    candidate: Mapped["Candidate"] = relationship()


class Skill(Base):
    """جدول مهارت‌ها: بانک اطلاعاتی مهارت‌های استاندارد بازار کار."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
