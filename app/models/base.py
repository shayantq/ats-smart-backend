import uuid
from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """کلاس پایه‌ی مشترک برای تمام مدل‌های ORM پروژه."""

    # این کلاس عمداً بدنه‌ای ندارد؛ فقط نقش یک نقطه‌ی اتصال مشترک
    # بین تمام مدل‌ها (User, Job, Application, ...) را دارد تا SQLAlchemy
    # بتواند همه‌ی جدول‌ها را زیر یک Metadata واحد بشناسد.
    pass


class TenantMixin:
    """
    جدول عملیاتیِ متعلق به یک سازمان (Tenant): ستون اجباری tenant_id ← companies.id.

    هر SELECT/UPDATE/DELETE روی این مدل‌ها در Context یک سازمان، خودکار به همان سازمان محدود
    می‌شود و ردیف جدید خودکار tenant_id سازمان را می‌گیرد — بنگرید app/core/tenancy.py.
    پشتیبان این فیلتر، پالیسی RLS همین جدول در خود PostgreSQL است.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)


class SharedTenantMixin:
    """
    مثل TenantMixin، ولی tenant_id اختیاری است: ردیف بدون tenant_id «استاندارد/عمومی» است و همه‌ی
    سازمان‌ها می‌خوانندش؛ ردیف دارای tenant_id «سفارشی» آن سازمان است (مثلاً جدول skills).
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[Optional[uuid.UUID]]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True, index=True)
