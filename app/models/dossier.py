"""دادهٔ انسانی و نسخه‌های تحلیل مستقل از خروجی قابل بازنویسی مدل‌اند."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, BigInteger, Identity, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedJSON
from app.models.base import Base, TenantMixin


class DossierReviewHead(TenantMixin, Base):
    __tablename__ = "dossier_review_heads"
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DossierReviewEvent(TenantMixin, Base):
    __tablename__ = "dossier_review_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    visibility: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(EncryptedJSON)


class DossierAnalysisVersion(TenantMixin, Base):
    __tablename__ = "dossier_analysis_versions"
    __table_args__ = (UniqueConstraint("application_id", "fingerprint", name="uq_dossier_version_fingerprint"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="CASCADE"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(EncryptedJSON)


class DossierReanalysisBatch(TenantMixin, Base):
    __tablename__ = "dossier_reanalysis_batches"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(EncryptedJSON)
