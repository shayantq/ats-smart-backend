"""
جداول هسته مرکزی سیستم (بخش ۸.۱ مستند فنی):
Users, Companies, Candidates, Jobs
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    """جدول کاربران: اطلاعات پایه و هویتی تمام افراد حاضر در سیستم."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="Candidate")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # روابط معکوس (Reverse Relations)
    owned_companies: Mapped[list["Company"]] = relationship(back_populates="owner")
    candidate_profile: Mapped["Candidate"] = relationship(back_populates="user", uselist=False)


class Company(Base):
    """جدول شرکت‌ها: مشخصات سازمان‌های خریدار پلتفرم."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=True)
    logo_url: Mapped[str] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    owner: Mapped["User"] = relationship(back_populates="owned_companies")
    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class Candidate(Base):
    """جدول کارجویان: اطلاعات اختصاصی افرادی که به دنبال شغل هستند."""

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)

    user: Mapped["User"] = relationship(back_populates="candidate_profile")


class Job(Base):
    """جدول مشاغل: آگهی‌های شغلی ثبت‌شده توسط شرکت‌ها."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Draft", nullable=False)  # Draft, Active, Closed

    company: Mapped["Company"] = relationship(back_populates="jobs")
