"""
پخش پیام به «تیم فنی» از طریق صندوق اعلان‌های داخل سایت (جدول notifications).

این همان «کانال پیام‌رسان داخل سایت» است که هم هشدارهای سیستم مانیتورینگ
(Alertmanager) و هم گزارش‌های موفقیت/شکست خط لوله‌ی CI/CD به آن می‌رسند —
بنگرید app/routers/ops.py. اعضای تیم فنی = کاربران فعال با یکی از نقش‌های
OPS_ALERT_RECIPIENT_ROLES (پیش‌فرض: Admin) در سازمانِ گرداننده‌ی پلتفرم (OPS_ALERT_TENANT_ID) —
Admin سازمان‌های مشتری هشدار زیرساخت دریافت نمی‌کنند.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Notification, User


def get_ops_recipient_roles() -> list[str]:
    return [role.strip() for role in settings.OPS_ALERT_RECIPIENT_ROLES.split(",") if role.strip()]


async def get_operator_tenant_id(db: AsyncSession) -> uuid.UUID | None:
    if settings.OPS_ALERT_TENANT_ID:
        return uuid.UUID(settings.OPS_ALERT_TENANT_ID)
    result = await db.execute(
        select(User.tenant_id)
        .where(User.role == "Admin", User.tenant_id.is_not(None))
        .order_by(User.created_at, User.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_ops_recipient_ids(db: AsyncSession) -> list[uuid.UUID]:
    operator_tenant_id = await get_operator_tenant_id(db)
    if operator_tenant_id is None:
        return []
    result = await db.execute(
        select(User.id).where(
            User.role.in_(get_ops_recipient_roles()),
            User.is_active.is_(True),
            User.tenant_id == operator_tenant_id,
        )
    )
    return list(result.scalars().all())


def add_broadcast(
    db: AsyncSession,
    recipient_ids: list[uuid.UUID],
    *,
    title: str,
    content: str | None,
    category: str,
) -> int:
    """
    برای هر عضو تیم فنی یک ردیف اعلان به Session اضافه می‌کند (commit با فراخوان است
    تا چند پیام — مثلاً چند هشدار یک گروه Alertmanager — در یک تراکنش ثبت شوند).
    خروجی: تعداد اعلان‌های اضافه‌شده.
    """
    for user_id in recipient_ids:
        db.add(Notification(user_id=user_id, title=title[:255], content=content, category=category))
    return len(recipient_ids)
