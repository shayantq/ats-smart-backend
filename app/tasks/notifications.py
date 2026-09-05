"""
کارهای پس‌زمینه‌ی مرتبط با اطلاع‌رسانی (ایمیل).

این توابع توسط یک فرآیند Worker مجزا اجرا می‌شوند (بنگرید app/worker.py)، نه
توسط سرور اصلی FastAPI — تا ارسال ایمیل هیچ‌وقت پاسخ HTTP کاربر را معطل نکند.
هر کدام از قالب‌های HTML موردنیازشان را با app/core/email_templates.py
Render می‌کنند و از app/core/email_service.py برای ارسال واقعی استفاده می‌کنند.
"""

import logging
from datetime import datetime

from app.core.config import settings
from app.core.email_service import send_email
from app.core.email_templates import render_email_template
from app.core.offer_letter import generate_offer_letter_pdf

logger = logging.getLogger("ats_smart.tasks.notifications")

# نگاشت هر وضعیت ماشین وضعیت (غیر از Offer که قالب اختصاصی خودش را دارد) به
# برچسب فارسی و پیام توضیحی مربوطه — بنگرید app/core/status_notifier.py که
# این نگاشت را برای تصمیم‌گیری «آیا اصلاً باید ایمیل فرستاد؟» هم استفاده می‌کند.
STATUS_NOTIFICATION_STAGES: dict[str, dict[str, str]] = {
    "Screening": {
        "label": "غربالگری اولیه",
        "message": "رزومه‌ی شما وارد مرحله‌ی غربالگری اولیه شده است.",
    },
    "Technical Interview": {
        "label": "مصاحبه فنی",
        "message": "شما به مرحله‌ی مصاحبه‌ی فنی راه یافته‌اید؛ به‌زودی برای هماهنگی زمان مصاحبه با شما تماس گرفته می‌شود.",
    },
    "HR Interview": {
        "label": "مصاحبه با کارشناس منابع انسانی",
        "message": "شما به مرحله‌ی مصاحبه با کارشناس منابع انسانی راه یافته‌اید.",
    },
    "Rejected": {
        "label": "عدم تأیید",
        "message": "با سپاس از وقتی که برای این فرصت شغلی گذاشتید، متأسفانه در حال حاضر امکان ادامه‌ی همکاری وجود ندارد.",
    },
}


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


def send_status_update_email_task(to_email: str, candidate_name: str, job_title: str, new_status: str) -> None:
    """
    ایمیل اطلاع‌رسانی تغییر وضعیت درخواست (مثلاً ورود به مرحله‌ی غربالگری یا
    مصاحبه). محرک: هر تغییر وضعیت موفق در ماشین وضعیت صلب که new_status آن در
    STATUS_NOTIFICATION_STAGES تعریف شده باشد (بنگرید app/core/status_notifier.py).
    """
    stage_info = STATUS_NOTIFICATION_STAGES.get(new_status)
    if stage_info is None:
        logger.warning("درخواست ارسال ایمیل برای وضعیتی بدون قالب تعریف‌شده نادیده گرفته شد | status=%s", new_status)
        return

    html_body = render_email_template(
        "status_update.html",
        candidate_name=candidate_name,
        job_title=job_title,
        stage_label=stage_info["label"],
        stage_message=stage_info["message"],
    )
    subject = f"به‌روزرسانی وضعیت درخواست شما برای «{job_title}»"

    try:
        send_email(to_email=to_email, subject=subject, html_body=html_body)
    except Exception as error:  # noqa: BLE001
        logger.error(
            "ارسال ایمیل تغییر وضعیت ناموفق بود | to=%s | new_status=%s | error=%s", to_email, new_status, error
        )
        raise


def send_job_offer_email_task(
    to_email: str, candidate_name: str, job_title: str, company_name: str | None
) -> None:
    """
    ایمیل رسمی پیشنهاد همکاری — محرک: تغییر وضعیت درخواست به «Offer» در
    بورد کانبان HR (معیار پذیرش اصلی این تسک).

    شامل یک فایل PDF پیوست (نامه‌ی رسمی پیشنهاد — app/core/offer_letter.py)
    و دو دکمه‌ی تعاملی «قبول/رد» در متن HTML ایمیل که کارجو را به پورتال
    کارجو (بخش «صندوق پیشنهادها») هدایت می‌کنند.
    """
    html_body = render_email_template(
        "job_offer.html",
        candidate_name=candidate_name,
        job_title=job_title,
        company_name=company_name,
        accept_url=settings.FRONTEND_ORIGIN,
        reject_url=settings.FRONTEND_ORIGIN,
    )
    subject = f"پیشنهاد همکاری رسمی برای موقعیت «{job_title}»"

    pdf_bytes = generate_offer_letter_pdf(
        candidate_name=candidate_name, job_title=job_title, company_name=company_name
    )

    try:
        send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            attachments=[("Job_Offer_Letter.pdf", pdf_bytes, "application/pdf")],
        )
    except Exception as error:  # noqa: BLE001
        logger.error("ارسال ایمیل پیشنهاد همکاری ناموفق بود | to=%s | error=%s", to_email, error)
        raise


def send_otp_email_task(to_email: str, otp_code: str, expires_in_minutes: int) -> None:
    """
    ایمیل کد یک‌بارمصرف (OTP) بازیابی رمز عبور — محرک: POST /api/v1/auth/forgot-password.
    """
    html_body = render_email_template("otp_reset.html", otp_code=otp_code, expires_in_minutes=expires_in_minutes)
    subject = "کد یک‌بارمصرف بازیابی رمز عبور"

    try:
        send_email(to_email=to_email, subject=subject, html_body=html_body)
    except Exception as error:  # noqa: BLE001
        logger.error("ارسال ایمیل OTP ناموفق بود | to=%s | error=%s", to_email, error)
        raise


def send_interview_reminder_email_task(
    to_email: str,
    recipient_name: str,
    candidate_name: str,
    interviewer_name: str,
    scheduled_at_iso: str,
    meeting_link: str,
) -> None:
    """
    ایمیل یادآور جلسه‌ی مصاحبه — محرک: دقیقاً ۲۴ ساعت پیش از شروع جلسه، توسط
    زمان‌بند rq-scheduler اجرا می‌شود (بنگرید app/core/interview_scheduler.py).
    به هر دو نفر (کارجو و مصاحبه‌کننده) جداگانه ارسال می‌شود؛ recipient_name
    نام همان گیرنده‌ی این نسخه‌ی خاص ایمیل است.
    """
    scheduled_at = datetime.fromisoformat(scheduled_at_iso)

    html_body = render_email_template(
        "interview_reminder.html",
        recipient_name=recipient_name,
        candidate_name=candidate_name,
        interviewer_name=interviewer_name,
        interview_date=scheduled_at.strftime("%Y-%m-%d"),
        interview_time=scheduled_at.strftime("%H:%M"),
        meeting_link=meeting_link,
    )
    subject = "یادآوری: مصاحبه‌ی شما فردا برگزار می‌شود"

    try:
        send_email(to_email=to_email, subject=subject, html_body=html_body)
    except Exception as error:  # noqa: BLE001
        logger.error("ارسال ایمیل یادآور مصاحبه ناموفق بود | to=%s | error=%s", to_email, error)
        raise
