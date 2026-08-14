"""اسکیمای خروجی مسیر آپلود رزومه (POST /api/v1/resumes/upload)."""

import uuid

from pydantic import BaseModel


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
