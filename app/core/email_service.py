"""
سرویس اتصال به میل‌سرور (SMTP) برای ارسال ایمیل‌های خروجی سیستم.

این ماژول فقط «نحوه‌ی واقعی فرستادن یک ایمیل» را کپسوله می‌کند (با کتابخانه‌ی
استاندارد smtplib پایتون، بدون هیچ وابستگی جانبی جدید). لایه‌ی صف/ناهمگام‌سازی
در app/core/notification_service.py و app/tasks/notifications.py پیاده‌سازی
شده — این ماژول هیچ‌وقت نباید مستقیماً از یک روتر FastAPI صدا زده شود، چون
همگام (Sync) است و می‌تواند چند ثانیه طول بکشد.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger("ats_smart.email_service")


def send_email(*, to_email: str, subject: str, html_body: str, text_body: str | None = None) -> None:
    """
    یک ایمیل واقعی از طریق SMTP می‌فرستد.

    این تابع همگام (Sync) است و باید همیشه از داخل یک Task پس‌زمینه (نه
    مستقیم از روتر FastAPI) صدا زده شود تا هیچ‌وقت درخواست HTTP کاربر را
    معطل نکند — بنگرید app/tasks/notifications.py.

    اگر ارسال ناموفق بود، استثنا را دوباره پرتاب می‌کند تا هم لایه‌ی
    بالادستی بتواند آن را با جزئیات مناسب لاگ کند، هم RQ خودش این Job را
    به‌عنوان failed علامت بزند (قابل پیگیری در سیستم صف).
    """
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to_email

    if text_body:
        message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], message.as_string())

    logger.info("ایمیل با موفقیت ارسال شد | to=%s | subject=%s", to_email, subject)
