"""
رمزنگاری داده‌های شخصی کارجو در دیتابیس (Encryption at Rest در لایه‌ی برنامه) — حریم خصوصی / GDPR.

- Fernet (AES-128-CBC + HMAC-SHA256، کتابخانه‌ی استاندارد cryptography) با MultiFernet: کلیدها از متغیر محیطی
  PII_ENCRYPTION_KEYS (جداشده با کاما). اولین کلید رمز می‌کند؛ کلیدهای بعدی فقط داده‌ی قدیمی را باز می‌کنند —
  چرخش کلید بدون قطعی (بنگرید «چرخش کلید» در docs/privacy/ARCHITECTURE.md و دستور reencrypt پایین همین فایل).
- نوع‌های ستون EncryptedText / EncryptedJSON: هنگام نوشتن رمز و هنگام خواندن خودکار باز می‌شوند؛ کد مسیرها و
  اسکیماهای API هیچ تغییری نمی‌بیند، ولی هر کسی که مستقیم دیتابیس را نگاه کند (DBeaver، psql، فایل پشتیبان)
  فقط متن رمزشده (gAAAAA…) می‌بیند.
- ایندکس کور (Blind Index): جستجوی متن رزومه روی متن رمزشده ممکن نیست؛ هر کلمه‌ی متن با HMAC-SHA256 و کلید
  جدای PII_BLIND_INDEX_KEY هش و در resumes.search_tokens (با ایندکس GIN) نگه داشته می‌شود. جستجو همان کلمات
  را هش و مقایسه می‌کند — بدون کلید، هیچ کلمه‌ای از روی هش قابل بازیابی یا حدس آفلاین نیست.

کلیدها هرگز چاپ، لاگ یا در پیام خطا آورده نمی‌شوند.
"""

import hashlib
import hmac
import json
import logging
import sys
from base64 import urlsafe_b64decode
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

logger = logging.getLogger("ats_smart.crypto")

# همه‌ی توکن‌های Fernet با بایت نسخه‌ی 0x80 شروع می‌شوند → در base64 همیشه «gAAAAA»
FERNET_PREFIX = "gAAAAA"
# طول هش هر کلمه در ایندکس کور (۱۲۸ بیت — احتمال برخورد برای واژگان رزومه‌ها عملاً صفر)
BLIND_INDEX_HEX_LENGTH = 32


class PiiKeyError(RuntimeError):
    """کلید رمزنگاری تنظیم نشده یا نامعتبر است؛ برنامه بدون آن بالا نمی‌آید."""


class PiiDecryptionError(RuntimeError):
    """متن رمزشده با هیچ‌کدام از کلیدهای فعلی باز نشد (کلید اشتباه یا داده‌ی دست‌کاری‌شده)."""


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    raw_keys = [key.strip() for key in settings.PII_ENCRYPTION_KEYS.split(",") if key.strip()]
    if not raw_keys:
        raise PiiKeyError("PII_ENCRYPTION_KEYS تنظیم نشده است (کلید رمزنگاری داده‌های شخصی).")
    try:
        return MultiFernet([Fernet(key.encode()) for key in raw_keys])
    except (ValueError, TypeError):
        # متن کلید عمداً در پیام نمی‌آید
        raise PiiKeyError("PII_ENCRYPTION_KEYS نامعتبر است: هر کلید باید Fernet (۳۲ بایت، base64 urlsafe) باشد.")


@lru_cache(maxsize=1)
def _blind_index_key() -> bytes:
    raw = settings.PII_BLIND_INDEX_KEY.strip()
    if not raw:
        raise PiiKeyError("PII_BLIND_INDEX_KEY تنظیم نشده است (کلید ایندکس کور جستجوی رزومه).")
    try:
        key = urlsafe_b64decode(raw)
    except ValueError:
        raise PiiKeyError("PII_BLIND_INDEX_KEY نامعتبر است: باید base64 urlsafe باشد.")
    if len(key) < 32:
        raise PiiKeyError("PII_BLIND_INDEX_KEY دست‌کم ۳۲ بایت باشد.")
    return key


def reset_key_cache() -> None:
    _fernet.cache_clear()
    _blind_index_key.cache_clear()


def validate_keys() -> None:
    """هنگام بالا آمدن API، Worker و مایگریشن: نبودِ کلید = توقف با پیام واضح، نه نوشتن داده‌ی رمزنشده."""
    _fernet()
    _blind_index_key()


def is_encrypted(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(FERNET_PREFIX)


def encrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError):
        raise PiiDecryptionError("رمزگشایی داده‌ی شخصی ناموفق بود (کلید نادرست یا داده‌ی دست‌کاری‌شده).")


def blind_index_token(word: str) -> str:
    digest = hmac.new(_blind_index_key(), word.lower().encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:BLIND_INDEX_HEX_LENGTH]


def blind_index_tokens(text: str | None) -> list[str] | None:
    """هش یکتای کلمات متن (همان نرمال‌سازی جستجو — app/core/search_query.py)، مرتب‌شده."""
    from app.core.search_query import resume_search_words

    if text is None:
        return None
    return sorted({blind_index_token(word) for word in resume_search_words(text)})


def _decrypt_stored(value: str | None) -> str | None:
    """
    مقدار رمزنشده‌ی قدیمی (نوشته‌شده توسط نسخه‌ی قبلی برنامه در چند دقیقه‌ی Rolling Update، پیش از جایگزینی
    کانتینرهای قدیمی) خطا نمی‌دهد و همان‌طور خوانده می‌شود؛ deploy.sh بلافاصله بعد از استقرار با
    «python -m app.core.crypto encrypt-legacy» آن‌ها را رمز می‌کند.
    """
    return decrypt_text(value) if is_encrypted(value) else value


class EncryptedText(TypeDecorator):
    """متن رمزشده در دیتابیس، متن عادی در برنامه."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> str | None:
        return encrypt_text(None if value is None else str(value))

    def process_result_value(self, value: str | None, dialect) -> str | None:
        return _decrypt_stored(value)


class EncryptedJSON(TypeDecorator):
    """دیکشنری/لیست در برنامه، JSON رمزشده در دیتابیس."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> str | None:
        return None if value is None else encrypt_text(json.dumps(value, ensure_ascii=False))

    def process_result_value(self, value: str | None, dialect) -> Any:
        return None if value is None else json.loads(_decrypt_stored(value))


# ---------------------------------------------------------------------------
# چرخش کلید:  python -m app.core.crypto reencrypt
#   ۱. کلید تازه را «اول» PII_ENCRYPTION_KEYS بگذارید و کلید قبلی را بعد از آن نگه دارید؛ مستقر کنید.
#   ۲. این دستور همه‌ی ردیف‌ها را با کلید تازه دوباره رمز (و ایندکس کور را از نو) می‌سازد.
#   ۳. کلید قبلی را از فهرست حذف کنید.
#
# رمز کردن باقی‌مانده‌ها:  python -m app.core.crypto encrypt-legacy
#   فقط ردیف‌هایی که مقدار رمزنشده دارند (نوشته‌شده توسط نسخه‌ی قبلی در Rolling Update) — deploy.sh بعد از هر
#   استقرار اجرا می‌کند؛ وقتی چیزی نیست، فقط یک کوئری شمارش است.
# ---------------------------------------------------------------------------
ENCRYPTED_FIELDS = {
    "candidates": ("first_name", "last_name", "phone", "location"),
    "resumes": ("raw_text", "parsed_data"),
}


async def _reencrypt(*, only_legacy: bool, batch_size: int = 200) -> dict[str, int]:
    from sqlalchemy import or_, select, type_coerce
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.tenancy import system_scope
    from app.db.session import AsyncSessionLocal
    from app.models import Candidate, Resume

    counts = {"candidates": 0, "resumes": 0}
    async with AsyncSessionLocal() as db:
        async with system_scope(db):
            for model, name in ((Candidate, "candidates"), (Resume, "resumes")):
                fields = ENCRYPTED_FIELDS[name]
                # type_coerce: مقایسه روی متن خام ستون (الگوی LIKE نباید خودش رمز شود)
                legacy = or_(
                    *(type_coerce(getattr(model, field), Text).not_like(f"{FERNET_PREFIX}%") for field in fields)
                )
                last_id = None
                while True:
                    query = select(model).order_by(model.id).limit(batch_size)
                    if only_legacy:
                        query = query.where(legacy)
                    if last_id is not None:
                        query = query.where(model.id > last_id)
                    rows = (await db.execute(query)).scalars().all()
                    if not rows:
                        break
                    for row in rows:
                        for field_name in fields:
                            flag_modified(row, field_name)
                        if model is Resume:
                            row.search_tokens = blind_index_tokens(row.raw_text)
                    await db.commit()
                    counts[name] += len(rows)
                    last_id = rows[-1].id
    return counts


if __name__ == "__main__":
    commands = {"reencrypt": False, "encrypt-legacy": True}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit("استفاده: python -m app.core.crypto reencrypt | encrypt-legacy")
    import asyncio

    validate_keys()
    print(json.dumps(asyncio.run(_reencrypt(only_legacy=commands[sys.argv[1]]))))
