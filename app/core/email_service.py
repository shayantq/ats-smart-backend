"""
سرویس اتصال به میل‌سرور (SMTP) برای ارسال ایمیل‌های خروجی سیستم.

این ماژول فقط «نحوه‌ی واقعی فرستادن یک ایمیل» را کپسوله می‌کند (با کتابخانه‌ی
استاندارد smtplib پایتون، بدون هیچ وابستگی جانبی جدید برای خودِ ارسال). لایه‌ی
صف/ناهمگام‌سازی در app/core/notification_service.py و app/tasks/notifications.py
پیاده‌سازی شده — این ماژول هیچ‌وقت نباید مستقیماً از یک روتر FastAPI صدا زده
شود، چون همگام (Sync) است و می‌تواند چند ثانیه طول بکشد.
"""

import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger("ats_smart.email_service")

# هر آیتم: (نام فایل، محتوای خام فایل، MIME type — مثلاً "application/pdf")
EmailAttachment = tuple[str, bytes, str]


def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    attachments: list[EmailAttachment] | None = None,
) -> None:
    """
    یک ایمیل واقعی از طریق SMTP می‌فرستد؛ اختیاری، با یک یا چند فایل پیوست
    (مثلاً PDF نامه‌ی پیشنهاد همکاری).

    این تابع همگام (Sync) است و باید همیشه از داخل یک Task پس‌زمینه (نه
    مستقیم از روتر FastAPI) صدا زده شود — بنگرید app/tasks/notifications.py.

    اگر ارسال ناموفق بود، استثنا را دوباره پرتاب می‌کند تا هم لایه‌ی
    بالادستی بتواند آن را با جزئیات مناسب لاگ کند، هم RQ خودش این Job را
    به‌عنوان failed علامت بزند (قابل پیگیری در سیستم صف).
    """
    message = MIMEMultipart("mixed")
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to_email

    body_part = MIMEMultipart("alternative")
    if text_body:
        body_part.attach(MIMEText(text_body, "plain", "utf-8"))
    body_part.attach(MIMEText(html_body, "html", "utf-8"))
    message.attach(body_part)

    for filename, file_bytes, mime_type in attachments or []:
        main_type, _, sub_type = mime_type.partition("/")
        attachment_part = MIMEBase(main_type or "application", sub_type or "octet-stream")
        attachment_part.set_payload(file_bytes)
        encoders.encode_base64(attachment_part)
        attachment_part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        message.attach(attachment_part)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], message.as_string())

    logger.info("ایمیل با موفقیت ارسال شد | to=%s | subject=%s | ضمیمه=%d", to_email, subject, len(attachments or []))
