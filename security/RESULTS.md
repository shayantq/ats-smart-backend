# نتایج تست امنیت — OWASP ZAP

تاریخ: ۲۱ مهر ۱۴۰۵ · ابزار: OWASP ZAP (stable، Docker) · گزارش‌های کامل: `security/reports/*.html`

## دامنه‌ی اسکن

| اسکن | روش | پوشش |
|---|---|---|
| **API** (`zap_api_scan`) | Passive + **Active** (حمله‌ی آزمایشی) از روی OpenAPI، با توکن Admin، از مسیر Nginx | ۱۲۱ آدرس — همه‌ی مسیرهای `/api/v1/*` |
| **سایت** (`zap_baseline_scan`) | Passive (Spider + بررسی پاسخ‌ها) | صفحات و فایل‌های فرانت‌اند |

حمله‌های آزمایش‌شده در Active Scan از جمله: SQL Injection (PostgreSQL و عمومی)، XSS (بازتابی/ذخیره‌شده)،
Command Injection، Path Traversal، Remote File Inclusion، SSRF (تلاش برای خواندن متادیتای سرور ابری)،
Server Side Template Injection، XXE، Buffer Overflow، Format String، CRLF Injection و افشای پیام‌های خطا.

## نتیجه‌ی نهایی

| اسکن | FAIL | PASS | Critical/High | Medium | Low |
|---|---|---|---|---|---|
| API | **۰** | ۱۱۹ | **۰** | **۰** | ۲ (توجیه‌شده — پایین) |
| سایت | **۰** | ۶۵ | **۰** | **۰** | **۰** |

✅ **هیچ آسیب‌پذیری بحرانی (Critical/High) یا متوسط (Medium) وجود ندارد.**
(ZAP سطح «Critical» جدا ندارد؛ بالاترین سطح آن High است که صفر است.)

## یافته‌های اسکن اول و اصلاح‌ها

| شدت | یافته | اصلاح |
|---|---|---|
| Medium | نبود Content-Security-Policy | CSP سخت‌گیرانه: فقط منابع همان دامنه، بدون اسکریپت/استایل inline، `frame-ancestors 'none'` |
| Low | نبود Cross-Origin-Embedder/Opener/Resource-Policy | هر سه اضافه شد |
| Low | نبود Permissions-Policy | دوربین/میکروفون/موقعیت/پرداخت/USB بسته شد |
| Low | `/api` (بدون اسلش) صفحه‌ی HTML برمی‌گرداند | پاسخ 404 JSON |

همه‌ی هدرها در `frontend/security-headers.conf` (روی همه‌ی پاسخ‌ها، از جمله API). پس از اصلاح، تست‌های E2E
(که هر خطای CSP در کنسول مرورگر را Fail می‌کنند) و نمودارهای داشبورد تحلیلی بدون خطا اجرا شدند.

## موارد Low باقی‌مانده (پذیرفته‌شده)

- **Unexpected Content-Type (×۱۱):** اسکنر API برای هر آدرسی JSON انتظار دارد؛ این آدرس‌ها مسیر API نیستند
  (مثلاً `/` یا `/latest/meta-data/`) و Nginx طبق طراحی SPA صفحه‌ی اصلی سایت را برمی‌گرداند. تلاش‌های SSRF
  برای خواندن متادیتای سرور ابری (`/latest/meta-data/`، `/computeMetadata/v1/`) فقط همین صفحه‌ی عادی را
  گرفتند — یعنی ناموفق بودند.
- **دو هدر روی `backend_api:8000/openapi.json`:** ZAP مستندات API را مستقیماً از داخل شبکه‌ی Docker خواند؛
  کاربران هرگز به این آدرس دسترسی ندارند (در Production بک‌اند پورت عمومی ندارد و همه‌ی ترافیک از Nginx
  با همه‌ی هدرهای امنیتی عبور می‌کند).

## خارج از دامنه‌ی ZAP (یافته‌های بازبینی کد، پیشنهاد برای تسک‌های بعدی)

- ثبت‌نام آزاد با نقش `Admin` (هر کسی می‌تواند خود را مدیر کند) — منطق کسب‌وکار، با اسکنر خودکار قابل کشف نیست.
- عدم بررسی `is_active` هنگام ورود/احراز هویت.
- دسترسی عمومی به فایل‌های رزومه از مسیر `/media`.
- HTTPS در این ریپو پیکربندی نشده (پیش‌نیاز Production).
