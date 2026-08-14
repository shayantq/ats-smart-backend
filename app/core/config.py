"""
تنظیمات مرکزی پروژه ATS Smart.
مقادیر حساس از فایل .env خوانده می‌شوند و هرگز داخل کد نوشته نمی‌شوند.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ATS Smart"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/smart_ats_db"
    REDIS_URL: str = "redis://localhost:6379/0"

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
