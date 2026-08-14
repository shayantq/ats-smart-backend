"""
لایه‌ی انتزاعی ذخیره‌سازی فایل (Storage Backend).

هدف: کد بالادستی (روتر آپلود رزومه) هیچ‌وقت مستقیماً با دیسک یا S3 صحبت
نمی‌کند؛ فقط متد save_file() را روی یک "backend" صدا می‌زند. این یعنی
می‌توان بین ذخیره‌سازی محلی (برای توسعه) و یک Object Storage واقعی
(AWS S3، یا هر سرویس S3-Compatible مثل Liara Object Storage، ArvanCloud
Object Storage، MinIO و ...) فقط با تغییر یک متغیر محیطی (STORAGE_BACKEND
در .env) جابه‌جا شد، بدون تغییر کد روتر.
"""

import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings

_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _build_object_key(candidate_id: uuid.UUID, original_filename: str) -> str:
    """
    نامی یکتا و امن برای فایل ذخیره‌شده می‌سازد: <candidate_id>/<uuid>_<نام‌پاک‌شده>
    تا هم تصادم نام فایل غیرممکن شود، هم فایل‌های هر کارجو در یک مسیر جدا از هم بمانند.
    """
    safe_name = _SAFE_FILENAME_PATTERN.sub("_", original_filename) or "resume"
    return f"{candidate_id}/{uuid.uuid4().hex}_{safe_name}"


class StorageBackend(ABC):
    """قرارداد مشترک همه‌ی بک‌اندهای ذخیره‌سازی فایل."""

    @abstractmethod
    async def save_file(
        self, *, candidate_id: uuid.UUID, filename: str, content: bytes, content_type: str
    ) -> str:
        """فایل را ذخیره می‌کند و آدرس قابل‌دسترسی (file_url) آن را برمی‌گرداند."""
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    """
    ذخیره‌سازی روی دیسک محلی سرور — پیش‌فرض توسعه (Development).
    فایل‌ها زیر MEDIA_ROOT/resumes ذخیره می‌شوند و از مسیر MEDIA_BASE_URL/resumes/...
    در دسترس‌اند (بنگرید mount شدن پوشه‌ی media در app/main.py).
    """

    def __init__(self) -> None:
        self._root = Path(settings.MEDIA_ROOT) / "resumes"
        self._root.mkdir(parents=True, exist_ok=True)

    async def save_file(
        self, *, candidate_id: uuid.UUID, filename: str, content: bytes, content_type: str
    ) -> str:
        object_key = _build_object_key(candidate_id, filename)
        destination = self._root / object_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return f"{settings.MEDIA_BASE_URL.rstrip('/')}/resumes/{object_key}"


class S3StorageBackend(StorageBackend):
    """
    ذخیره‌سازی روی یک Object Storage واقعی، سازگار با پروتکل S3
    (AWS S3، Liara Object Storage، ArvanCloud Object Storage، MinIO و ...).
    فقط زمانی فعال می‌شود که STORAGE_BACKEND=s3 در .env تنظیم شده باشد.
    """

    def __init__(self) -> None:
        # ایمپورت تنبل (Lazy Import): تا این بک‌اند واقعاً استفاده نشود، نصب‌نبودن
        # boto3 مانع بالا آمدن سرور در حالت local (پیش‌فرض توسعه) نمی‌شود.
        import boto3

        if not settings.S3_BUCKET_NAME:
            raise RuntimeError("S3_BUCKET_NAME در .env تنظیم نشده است.")

        self._bucket = settings.S3_BUCKET_NAME
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.S3_SECRET_KEY or None,
            region_name=settings.S3_REGION,
        )

    async def save_file(
        self, *, candidate_id: uuid.UUID, filename: str, content: bytes, content_type: str
    ) -> str:
        object_key = _build_object_key(candidate_id, filename)
        self._client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=content,
            ContentType=content_type,
        )
        return self._build_public_url(object_key)

    def _build_public_url(self, object_key: str) -> str:
        if settings.S3_PUBLIC_BASE_URL:
            return f"{settings.S3_PUBLIC_BASE_URL.rstrip('/')}/{object_key}"
        if settings.S3_ENDPOINT_URL:
            return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self._bucket}/{object_key}"
        return f"https://{self._bucket}.s3.{settings.S3_REGION}.amazonaws.com/{object_key}"


_storage_backend_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """Singleton ساده: بک‌اند ذخیره‌سازی را طبق تنظیمات .env یک‌بار می‌سازد و مجدداً استفاده می‌کند."""
    global _storage_backend_instance
    if _storage_backend_instance is None:
        if settings.STORAGE_BACKEND == "s3":
            _storage_backend_instance = S3StorageBackend()
        else:
            _storage_backend_instance = LocalStorageBackend()
    return _storage_backend_instance
