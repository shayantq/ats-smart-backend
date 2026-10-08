"""
مسیرهای عملیاتی (DevOps) — مقصد وب‌هوک سرویس‌های زیرساختی، نه کاربران:
- POST /api/v1/ops/alerts   وب‌هوک Alertmanager: هشدارهای سرور (RAM بالای ۸۵٪، نرخ خطای بالای ۵٪ و ...)
- POST /api/v1/ops/events   گزارش خط لوله‌ی CI/CD (موفقیت/شکست تست، استقرار و ...)

هر دو پیام دریافتی را به صندوق اعلان‌های داخل سایت همه‌ی اعضای تیم فنی
(app/core/ops_notifier.py) تبدیل می‌کنند.

احراز هویت: این مسیرها توکن JWT کاربر ندارند (فرستنده یک سرویس است)؛ به‌جایش
یک توکن مشترک Bearer (OPS_WEBHOOK_TOKEN در .env) با مقایسه‌ی Constant-Time
بررسی می‌شود. اگر OPS_WEBHOOK_TOKEN تنظیم نشده باشد، مسیرها با 503 کاملاً
غیرفعال‌اند — هیچ‌وقت یک webhook باز و بدون احراز هویت روی سرور نمی‌ماند.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ops_notifier import add_broadcast, get_ops_recipient_ids
from app.db.session import get_db
from app.schemas.ops import AlertmanagerAlert, AlertmanagerWebhookPayload, OpsDeliveryResponse, OpsEventRequest

router = APIRouter()

_ops_bearer = HTTPBearer(auto_error=False)

_SEVERITY_ICONS = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
_EVENT_LEVEL_ICONS = {"success": "✅", "failure": "❌", "info": "ℹ️"}


def verify_ops_token(credentials: HTTPAuthorizationCredentials | None = Depends(_ops_bearer)) -> None:
    if not settings.OPS_WEBHOOK_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="مسیرهای عملیاتی غیرفعال‌اند (OPS_WEBHOOK_TOKEN تنظیم نشده است).",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), settings.OPS_WEBHOOK_TOKEN.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توکن عملیاتی نامعتبر است.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def format_alert_message(alert: AlertmanagerAlert) -> tuple[str, str]:
    """یک هشدار Alertmanager را به (عنوان، متن) قابل‌خواندن برای پنل اعلان‌ها تبدیل می‌کند."""
    alert_name = alert.labels.get("alertname", "UnknownAlert")
    severity = alert.labels.get("severity", "warning")

    if alert.status == "resolved":
        title = f"✅ [برطرف شد] {alert_name}"
    else:
        title = f"{_SEVERITY_ICONS.get(severity, '🟠')} [{severity.upper()}] {alert_name}"

    lines = []
    if summary := alert.annotations.get("summary"):
        lines.append(summary)
    if description := alert.annotations.get("description"):
        lines.append(description)
    if instance := alert.labels.get("instance"):
        lines.append(f"منبع: {instance}")
    if alert.startsAt is not None:
        lines.append(f"شروع: {alert.startsAt.isoformat()}")
    if alert.status == "resolved" and alert.endsAt is not None:
        lines.append(f"پایان: {alert.endsAt.isoformat()}")

    return title, "\n".join(lines)


@router.post(
    "/alerts",
    response_model=OpsDeliveryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Ops"],
    summary="وب‌هوک Alertmanager — ارسال هشدارهای سرور به اعلان‌های داخل سایت تیم فنی",
    dependencies=[Depends(verify_ops_token)],
)
async def receive_alertmanager_webhook(
    payload: AlertmanagerWebhookPayload,
    db: AsyncSession = Depends(get_db),
) -> OpsDeliveryResponse:
    recipient_ids = await get_ops_recipient_ids(db)

    delivered = 0
    for alert in payload.alerts:
        title, content = format_alert_message(alert)
        delivered += add_broadcast(db, recipient_ids, title=title, content=content, category="alert")

    await db.commit()
    return OpsDeliveryResponse(delivered_notifications=delivered, recipients=len(recipient_ids))


@router.post(
    "/events",
    response_model=OpsDeliveryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Ops"],
    summary="گزارش رویداد عملیاتی (مثلاً نتیجه‌ی خط لوله‌ی CI/CD) به اعلان‌های داخل سایت تیم فنی",
    dependencies=[Depends(verify_ops_token)],
)
async def receive_ops_event(
    payload: OpsEventRequest,
    db: AsyncSession = Depends(get_db),
) -> OpsDeliveryResponse:
    recipient_ids = await get_ops_recipient_ids(db)

    title = f"{_EVENT_LEVEL_ICONS[payload.level]} {payload.title}"
    delivered = add_broadcast(db, recipient_ids, title=title, content=payload.content, category=payload.category)

    await db.commit()
    return OpsDeliveryResponse(delivered_notifications=delivered, recipients=len(recipient_ids))
