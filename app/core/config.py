"""
تنظیمات مرکزی پروژه ATS Smart
تمام مقادیر حساس (پسورد، سکرت و ...) از فایل .env خوانده می‌شوند
و هرگز به صورت مستقیم داخل کد نوشته نمی‌شوند (جهت پیشگیری از هشدار امنیتی).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # اطلاعات کلی پروژه
    PROJECT_NAME: str = "ATS Smart"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # دیتابیس (در اسپرینت‌های بعدی تکمیل می‌شود)
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/smart_ats_db"

    # ردیس (در اسپرینت‌های بعدی تکمیل می‌شود)
    REDIS_URL: str = "redis://localhost:6379/0"

    # امنیت / JWT (در اسپرینت‌های بعدی تکمیل می‌شود)
    SECRET_KEY: str = "changeme-in-env-file"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
