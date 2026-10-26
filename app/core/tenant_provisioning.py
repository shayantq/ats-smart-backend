"""
ساخت سازمان (Tenant) تازه — مشترک بین ثبت‌نام Admin (app/routers/auth.py) و اسکریپت‌های داده‌ی آزمایشی
(E2E، تست بار، اسکن امنیتی، اسکریپت‌های k8s). کار سطح پلتفرم است: در درخواست API فقط داخل
system_scope صدا زده می‌شود؛ اسکریپت‌ها و Worker ها ذاتاً در حالت system اجرا می‌شوند.
"""

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, User


async def provision_tenant(db: AsyncSession, *, name: str, owner: User) -> Company:
    """سازمان را با مالک (Admin) می‌سازد و مالک را عضو آن می‌کند. commit با فراخواننده است."""
    if owner.id is None or owner not in db:
        db.add(owner)
        await db.flush()
    company = Company(name=name, owner_id=owner.id)
    db.add(company)
    await db.flush()
    owner.tenant_id = company.id
    return company


async def delete_owned_tenants(db: AsyncSession, owner_ids: list) -> int:
    """
    پاک‌سازی داده‌ی آزمایشی: سازمان‌هایی که مالکشان یکی از owner_ids است حذف می‌شوند (پس از حذف رکوردهای
    عملیاتی‌شان توسط فراخواننده). عضویت کاربران در آن‌ها اول برداشته می‌شود تا کلید خارجی مانع نشود.
    """
    tenant_ids = (await db.execute(select(Company.id).where(Company.owner_id.in_(owner_ids)))).scalars().all()
    if tenant_ids:
        await db.execute(update(User).where(User.tenant_id.in_(tenant_ids)).values(tenant_id=None))
        await db.execute(delete(Company).where(Company.id.in_(tenant_ids)))
    return len(tenant_ids)
