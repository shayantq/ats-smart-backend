"""
اسکیمای خروجی API های تجمیعی داشبورد تحلیلی (Data Aggregation):
GET /api/v1/analytics/funnel
GET /api/v1/analytics/applications-trend
"""

import uuid
from datetime import date as date_type
from typing import Optional

from pydantic import BaseModel


class FunnelStageCount(BaseModel):
    """یک ردیف از قیف استخدام — مستقیماً قابل مصرف در کتابخانه‌های نمودارساز (funnel/bar chart)."""

    stage: str
    count: int


class RecruitmentFunnelResponse(BaseModel):
    job_id: Optional[uuid.UUID] = None
    stages: list[FunnelStageCount]


class DailyApplicationCount(BaseModel):
    """یک نقطه از نمودار سری‌زمانی — یک روز و تعداد درخواست‌های ثبت‌شده در آن روز."""

    date: date_type
    count: int


class ApplicationsTrendResponse(BaseModel):
    days: int
    job_id: Optional[uuid.UUID] = None
    series: list[DailyApplicationCount]
