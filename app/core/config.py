"""
تنظیمات مرکزی پروژه ATS Smart.
مقادیر حساس از فایل .env خوانده می‌شوند و هرگز داخل کد نوشته نمی‌شوند.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ATS Smart"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    # نسخه‌ی منتشرشده (sha کامیت؛ هنگام بیلد ایمیج با --build-arg APP_VERSION) — در /health
    APP_VERSION: str = "dev"

    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/smart_ats_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    # ظرفیت Connection Pool دیتابیس در «هر» پردازه‌ی بک‌اند. سقف کل اتصال‌ها =
    # (POOL_SIZE + MAX_OVERFLOW) × تعداد کانتینرهای بک‌اند — باید زیر max_connections پستگرس بماند
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    # نقش دیتابیسی که درخواست‌های API در هر تراکنش به آن سوئیچ می‌کنند (SET LOCAL ROLE) تا پالیسی‌های
    # Row-Level Security چندمستاجری اعمال شوند — بنگرید app/core/tenancy.py و مایگریشن d2f6b8a41c37
    DB_RLS_ROLE: str = "ats_app"

    # ---- Zero-Trust: احراز هویت سرویس‌به‌سرویس (app/core/service_auth.py) ----
    # نام همین سرویس در توکن‌های داخلی (iss برای فرستنده، aud برای گیرنده)، مثلاً backend-api / worker
    SERVICE_NAME: str = "backend-api"
    # فرستنده: مسیر فایل کلید خصوصی ES256 همین سرویس (Secret مانت‌شده؛ هرگز متغیر محیطی یا فایل تنظیمات)
    SERVICE_AUTH_PRIVATE_KEY_FILE: str = ""
    # گیرنده: پوشه‌ی کلیدهای عمومی سرویس‌های مجاز — هر فایل <نام-سرویس>.pem
    SERVICE_AUTH_PUBLIC_KEYS_DIR: str = ""
    # نشانی داخلی بک‌اند برای فراخوانی سرویس‌به‌سرویس (مثلاً http://backend_api:8000)؛ خالی = مسیر قدیمی
    INTERNAL_API_URL: str = ""

    SECRET_KEY: str = "changeme-in-env-file"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # دامنه‌ی رسمی فرانت‌اند که اجازه‌ی صحبت با این API را دارد (برای CORS)
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # ---- ذخیره‌سازی فایل رزومه (Resume Storage) ----
    # "local": ذخیره روی دیسک سرور (پیش‌فرض توسعه) — "s3": هر Object Storage سازگار با S3
    # (AWS S3، Liara Object Storage، ArvanCloud Object Storage، MinIO و ...)
    STORAGE_BACKEND: str = "local"
    MEDIA_ROOT: str = "media"
    MEDIA_BASE_URL: str = "http://localhost:8000/media"

    S3_ENDPOINT_URL: str = ""  # برای AWS خالی بگذارید؛ برای S3-Compatible آدرس endpoint را وارد کنید
    S3_BUCKET_NAME: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION: str = "us-east-1"
    S3_PUBLIC_BASE_URL: str = ""  # اگر bucket دامنه‌ی عمومی یا CDN اختصاصی دارد

    # ---- موتور استخراج متن رزومه (OCR Engine) ----
    # زبان‌های Tesseract برای OCR رزومه‌های اسکن‌شده/تصویری (فارسی+انگلیسی به‌صورت پیش‌فرض)
    OCR_LANGUAGES: str = "fas+eng"
    # اگر باینری tesseract در PATH سیستم نبود، مسیر کامل exe را اینجا بده (مخصوصاً روی ویندوز)
    TESSERACT_CMD_PATH: str = ""

    # ---- سرویس ایمیل (SMTP) — برای زیرسیستم اطلاع‌رسانی رویدادمحور (Notification Service) ----
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "no-reply@ats-smart.local"
    SMTP_FROM_NAME: str = "ATS Smart"

    # ---- عملیات و مانیتورینگ (DevOps) ----
    # توکن مشترک (Bearer) که Alertmanager و خط لوله‌ی CI/CD با آن به مسیرهای
    # /api/v1/ops/* پیام می‌فرستند. خالی = این مسیرها کاملاً غیرفعال (503) — تا
    # هیچ‌وقت یک webhook بدون احراز هویت روی سرور باز نماند.
    OPS_WEBHOOK_TOKEN: str = ""
    # نقش‌هایی که «تیم فنی» حساب می‌شوند و هشدارهای سرور/گزارش‌های استقرار را
    # در صندوق اعلان‌های داخل سایت دریافت می‌کنند (جداشده با کاما)
    OPS_ALERT_RECIPIENT_ROLES: str = "Admin"
    # چندمستاجری: تیم فنی = کارمندانِ سازمانِ گرداننده‌ی پلتفرم، نه Admin سازمان‌های مشتری (هشدار
    # زیرساخت نباید به مشتری‌ها نشت کند). خالی = سازمانِ قدیمی‌ترین کاربر Admin (سازمان گرداننده)
    OPS_ALERT_TENANT_ID: str = ""

    # ---- هوش مصنوعی مولد (تولید سؤال مصاحبه — app/genai) ----
    # هر سرویس سازگار با پروتکل Chat Completions (ابری یا داخل کلاستر)؛ ارائه‌دهنده و مدل فقط با همین
    # تنظیمات انتخاب می‌شوند و در کد نامی از آن‌ها نیست. خالی بودن آدرس یا مدل = قابلیت غیرفعال (503).
    GENAI_BASE_URL: str = ""
    GENAI_API_KEY: str = ""
    GENAI_MODEL: str = ""
    GENAI_TIMEOUT_SECONDS: float = 240.0
    GENAI_MAX_OUTPUT_TOKENS: int = 4096
    GENAI_TEMPERATURE: float = 0.3
    # json_schema: خروجی مقید به JSON Schema سمت سرویس (پیش‌فرض)؛ json_object: فقط JSON معتبر و
    # اعتبارسنجی Schema سمت ما — برای سرویس‌هایی که response_format از نوع json_schema را ندارند
    GENAI_STRUCTURED_OUTPUT: str = "json_schema"

    @property
    def internal_api_enabled(self) -> bool:
        """این پردازه می‌تواند درخواست داخلی امضاشده به بک‌اند بفرستد."""
        return bool(self.INTERNAL_API_URL and self.SERVICE_AUTH_PRIVATE_KEY_FILE)

    @property
    def genai_enabled(self) -> bool:
        return bool(self.GENAI_BASE_URL and self.GENAI_MODEL)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
