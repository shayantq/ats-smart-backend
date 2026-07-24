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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
