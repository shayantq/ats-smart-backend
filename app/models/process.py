"""
جداول فرآیندی و مهارتی سیستم (Process and Skill Tables (ساب تسک دوم)): شامل جداولی که فرآیندهای اصلی سیستم را مدیریت می‌کنند و همچنین بانک اطلاعاتی مهارت‌های استاندارد بازار کار.
Applications, Interviews, Resumes, Skills
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Application(Base):
    """جدول درخواست‌ها: حلقه‌ی وصل کارجو به پوزیشن شغلی و بورد کانبان."""

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    current_status: Mapped[str] = mapped_column(String(50), default="Draft", nullable=False)
    score_ai: Mapped[int] = mapped_column(Integer, nullable=True)

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
    scheduled_at: Mapped[datetime] = mapped_column(nullable=True)
    meeting_link: Mapped[str] = mapped_column(String(500), nullable=True)

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

    candidate: Mapped["Candidate"] = relationship()


class Skill(Base):
    """جدول مهارت‌ها: بانک اطلاعاتی مهارت‌های استاندارد بازار کار."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
