"""
سرویس اطلاع‌رسانی (Notification Service) — نقطه‌ی ورود سطح بالا برای بقیه‌ی
اپلیکیشن (مثلاً روترها) تا رویدادهای نیازمند اطلاع‌رسانی را ثبت کنند، بدون
این‌که خودشان مستقیماً با صف Redis یا توابع Task آشنا باشند.

هر متد این ماژول فقط یک Task را به صف Redis اضافه می‌کند (با همان مکانیزم
ناهمگام و مقاوم در برابر خطای app/core/queue.py) و بلافاصله برمی‌گردد — طبق
الگوی مشابه app/routers/resumes.py، فراخوان باید این متدها را با
asyncio.create_task صدا بزند (نه await مستقیم) تا پاسخ HTTP جاری هرگز معطل
ارتباط با Redis نماند.
"""

from app.core.queue import enqueue_task
from app.tasks.notifications import send_welcome_email_task


async def notify_new_user_registered(email: str, first_name: str | None = None) -> str | None:
    """
    محرک (Trigger) رویداد «ثبت‌نام کاربر جدید»: یک Task ایمیل خوش‌آمدگویی/
    تأیید اصالت حساب را به صف Redis اضافه می‌کند.

    خروجی (شناسه‌ی Job در صف، یا None در صورت شکست افزودن به صف) صرفاً برای
    لاگ‌گیری اختیاری در فراخوان است؛ نبود مقدار به‌معنای شکست خودِ ثبت‌نام
    نیست — enqueue_task خودش خطا را لاگ می‌کند و استثنایی پرتاب نمی‌کند.
    """
    return await enqueue_task(send_welcome_email_task, email, first_name)
