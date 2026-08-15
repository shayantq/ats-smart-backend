"""
کارهای پس‌زمینه‌ی مرتبط با پردازش رزومه.

این توابع توسط یک فرآیند Worker مجزا اجرا می‌شوند، نه توسط سرور اصلی FastAPI.
برای اجرای Worker (باید هم‌زمان با سرور، در یک ترمینال جدا، روشن بماند):

    rq worker --url redis://localhost:6379/0 default
"""

import logging

logger = logging.getLogger("ats_smart.tasks.resume")


def process_resume_task(application_id: str, file_url: str) -> None:
    """
    نقطه‌ی شروع پردازش هوش مصنوعی رزومه (استخراج مهارت‌ها، امتیازدهی و ...).

    پیاده‌سازی کامل موتور هوش مصنوعی خارج از محدوده‌ی این تسک (زیرساخت صف) است؛
    فعلاً فقط دریافت موفق کار توسط Worker را لاگ می‌کند تا عملکرد صحیح کل
    زیرساخت صف (از ثبت درخواست تا اجرای Worker) قابل تأیید باشد.
    """
    logger.info(
        "شروع پردازش پس‌زمینه‌ی رزومه | application_id=%s | file_url=%s",
        application_id,
        file_url,
    )
    # TODO(اسپرینت موتور هوش مصنوعی): استخراج متن رزومه، امتیازدهی، و به‌روزرسانی
    # ستون score_ai در جدول applications.
