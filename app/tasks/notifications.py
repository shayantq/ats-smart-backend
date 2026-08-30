"""
کارهای پس‌زمینه‌ی مرتبط با اطلاع‌رسانی (ایمیل).

این توابع توسط یک فرآیند Worker مجزا اجرا می‌شوند (بنگرید app/worker.py)، نه
توسط سرور اصلی FastAPI — تا ارسال ایمیل هیچ‌وقت پاسخ HTTP کاربر را معطل نکند.
"""

import logging

from app.core.email_service import send_email

logger = logging.getLogger("ats_smart.tasks.notifications")


def send_welcome_email_task(to_email: str, first_name: str | None = None) -> None:
    """
    ایمیل خوش‌آمدگویی و تأیید اصالت حساب.

    محرک (Trigger): بلافاصله بعد از ثبت‌نام موفق یک کاربر جدید، به‌صورت
    ناهمگام به صف Redis اضافه می‌شود (بنگرید app/routers/auth.py و
    app/core/notification_service.py) — مسیر /auth/register هرگز منتظر
    اتمام واقعی ارسال ایمیل نمی‌ماند.
    """
    display_name = first_name or to_email.split("@")[0]
    subject = "به ATS Smart خوش آمدید 🎉"

    html_body = f"""
    <div style="font-family: Tahoma, sans-serif; direction: rtl; text-align: right;">
        <h2>سلام {display_name} عزیز،</h2>
        <p>حساب کاربری شما در پلتفرم <strong>ATS Smart</strong> با موفقیت ساخته شد.</p>
        <p>از همین امروز می‌توانید وارد حساب خود شوید و از امکانات پلتفرم استفاده کنید.</p>
        <p>با احترام،<br>تیم ATS Smart</p>
    </div>
    """
    text_body = (
        f"سلام {display_name} عزیز،\n\n"
        "حساب کاربری شما در پلتفرم ATS Smart با موفقیت ساخته شد.\n\n"
        "با احترام،\nتیم ATS Smart"
    )

    try:
        send_email(to_email=to_email, subject=subject, html_body=html_body, text_body=text_body)
    except Exception as error:  # noqa: BLE001 - لاگ واضح قبل از اجازه دادن به RQ برای علامت‌گذاری Job به‌عنوان failed
        logger.error("ارسال ایمیل خوش‌آمدگویی ناموفق بود | to=%s | error=%s", to_email, error)
        raise
