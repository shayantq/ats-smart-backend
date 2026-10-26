"""اسکیمای خروجی مسیرهای رزومه (POST /api/v1/resumes/upload و GET /api/v1/resumes/{resume_id})."""

import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ResumeUploadResponse(BaseModel):
    """
    ساختار پاسخ موفق (202 Accepted).

    کد 202 عمداً انتخاب شده (نه 200 یا 201): چون پس از ثبت فایل و درخواست،
    پردازش هوش مصنوعی رزومه به‌صورت ناهمگام در پس‌زمینه شروع می‌شود و سرور
    منتظر اتمامش نمی‌ماند.
    """

    application_id: uuid.UUID
    status: str
    message: str


class ResumeDetailResponse(BaseModel):
    """جزئیات یک رزومه برای HR (GET /api/v1/resumes/{resume_id})."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    tenant_id: uuid.UUID
    file_url: str
    parsed_data: Optional[dict[str, Any]] = None
    skill_analysis: Optional[dict[str, Any]] = None
