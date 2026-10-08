"""
اسکیمای مسیرهای عملیاتی (DevOps) که سرویس‌های زیرساختی — نه کاربران — صدا می‌زنند:
- POST /api/v1/ops/alerts   وب‌هوک Alertmanager (قالب استاندارد Webhook نسخه‌ی ۴)
- POST /api/v1/ops/events   گزارش رویدادهای عملیاتی، مثل نتیجه‌ی خط لوله‌ی CI/CD
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.sanitize import strip_html_tags


class AlertmanagerAlert(BaseModel):
    """
    یک هشدار منفرد داخل payload وب‌هوک Alertmanager. فیلدهای ناشناخته عمداً
    نادیده گرفته می‌شوند (extra="ignore") تا ارتقای نسخه‌ی Alertmanager که
    فیلد جدیدی اضافه می‌کند، این مسیر را نشکند.
    """

    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: Optional[datetime] = None
    endsAt: Optional[datetime] = None


class AlertmanagerWebhookPayload(BaseModel):
    """https://prometheus.io/docs/alerting/latest/configuration/#webhook_config"""

    model_config = ConfigDict(extra="ignore")

    version: str = "4"
    status: Literal["firing", "resolved"]
    receiver: str = ""
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)


class OpsEventRequest(BaseModel):
    """گزارش یک رویداد عملیاتی (مثلاً «استقرار نسخه‌ی abc123 موفق بود») از طرف CI/CD."""

    title: str = Field(min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, max_length=4000)
    level: Literal["success", "failure", "info"] = "info"
    category: str = Field(default="deployment", min_length=1, max_length=50)

    @field_validator("title", "content", "category", mode="before")
    @classmethod
    def sanitize_text(cls, value: Optional[str]) -> Optional[str]:
        """دفاع XSS مشترک پروژه — این متن‌ها مستقیم در پنل اعلان‌های فرانت‌اند نمایش داده می‌شوند."""
        return strip_html_tags(value)


class OpsDeliveryResponse(BaseModel):
    """تعداد اعلان‌های ساخته‌شده (= تعداد هشدار/رویداد × تعداد اعضای تیم فنی)."""

    delivered_notifications: int
    recipients: int
