"""
پخش پیام به «تیم فنی» از طریق صندوق اعلان‌های داخل سایت (جدول notifications).

این همان «کانال پیام‌رسان داخل سایت» است که هم هشدارهای سیستم مانیتورینگ
(Alertmanager) و هم گزارش‌های موفقیت/شکست خط لوله‌ی CI/CD به آن می‌رسند —
بنگرید app/routers/ops.py. اعضای تیم فنی = همه‌ی کاربران فعال با یکی از
نقش‌های OPS_ALERT_RECIPIENT_ROLES (پیش‌فرض: Admin).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Notification, User


def get_ops_recipient_roles() -> list[str]:
    return [role.strip() for role in settings.OPS_ALERT_RECIPIENT_ROLES.split(",") if role.strip()]


async def get_ops_recipient_ids(db: AsyncSession) -> list[uuid.UUID]:
    result = await db.execute(select(User.id).where(User.role.in_(get_ops_recipient_roles()), User.is_active.is_(True)))
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
