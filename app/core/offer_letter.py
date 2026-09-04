"""
تولید نسخه‌ی PDF نامه‌ی رسمی پیشنهاد همکاری (Job Offer Letter) — پیوست ایمیل
پیشنهاد شغلی (بنگرید app/tasks/notifications.py: send_job_offer_email_task).

⚠️ محدودیت شناخته‌شده و صادقانه: محتوای این PDF عمداً به زبان انگلیسی تولید
می‌شود. فونت‌های پیش‌فرض ReportLab (Helvetica) از حروف فارسی/عربی پشتیبانی
نمی‌کنند و رندر درست متن فارسی در PDF نیاز به Reshape/BiDi (کتابخانه‌هایی
مثل arabic-reshaper و python-bidi) و embed کردن یک فونت فارسی TTF دارد که
خارج از محدوده‌ی این تسک است؛ بدون آن‌ها، متن فارسی در PDF به‌هم‌ریخته
(کاراکترهای جدا از هم و بدون اتصال) نمایش داده می‌شود. یک نامه‌ی رسمی
انگلیسی برای این منظور هم رایج و کاملاً قابل‌قبول است.
"""

import io
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

_LEFT_MARGIN = 72
_LINE_HEIGHT = 20


def generate_offer_letter_pdf(*, candidate_name: str, job_title: str, company_name: str | None) -> bytes:
    """یک PDF ساده و رسمی از نامه‌ی پیشنهاد همکاری می‌سازد و بایت‌های خام فایل را برمی‌گرداند."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(page_width / 2, page_height - 90, "Official Job Offer Letter")

    pdf.setFont("Helvetica", 12)
    company_display_name = company_name or "our company"
    lines = [
        f"Date: {date.today().isoformat()}",
        "",
        f"Dear {candidate_name},",
        "",
        f'We are pleased to offer you the position of "{job_title}"',
        f"at {company_display_name}.",
        "",
        "This letter confirms our intent to proceed with your employment,",
        "subject to your acceptance. Further details regarding compensation,",
        "start date, and terms will be shared upon your confirmation.",
        "",
        "Please respond to this offer via the candidate portal (Accept/Reject),",
        "or by clicking the corresponding button in the offer email.",
        "",
        "We look forward to welcoming you to the team.",
        "",
        "Best regards,",
        "ATS Smart Recruitment Team",
    ]

    y_position = page_height - 150
    for line in lines:
        pdf.drawString(_LEFT_MARGIN, y_position, line)
        y_position -= _LINE_HEIGHT

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()
