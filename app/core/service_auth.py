"""
احراز هویت سرویس‌به‌سرویس (Zero-Trust): هیچ سرویسی صرفاً چون «داخل شبکه» است، مورد اعتماد نیست.

هر درخواست داخلی (مثلاً Worker هوش مصنوعی ← بک‌اند برای خواندن پروفایل کارجو) یک توکن JWT کوتاه‌عمر در
هدر X-Internal-Auth دارد:

    الگوریتم   ES256 (ECDSA P-256) — نامتقارن: هر سرویس فرستنده کلید خصوصی خودش را دارد و گیرنده فقط
               کلیدهای عمومی را؛ لو رفتن کلید یک سرویس، امکان جعل هویت سرویس‌های دیگر را نمی‌دهد.
    Header     kid = نام سرویس فرستنده (برای انتخاب کلید عمومی)
    Claims     iss/sub = سرویس فرستنده · aud = سرویس گیرنده · iat/nbf/exp (حداکثر ۵ دقیقه) · jti یکتا ·
               typ = "service" · tid (اختیاری) = سازمانی که درخواست به آن محدود است (RLS گیرنده)

کلیدها فقط از فایل خوانده می‌شوند (Secret مانت‌شده در Kubernetes / Docker Compose)، نه از متغیر محیطی:
    SERVICE_AUTH_PRIVATE_KEY_FILE   فرستنده — کلید خصوصی PEM همین سرویس
    SERVICE_AUTH_PUBLIC_KEYS_DIR    گیرنده — پوشه‌ی <نام-سرویس>.pem برای هر سرویس مجاز

چرخش کلید: کلید جدید کنار قبلی ساخته می‌شود، فایل عمومی جایگزین و سرویس‌ها ری‌استارت می‌شوند (توکن‌ها
حداکثر چند دقیقه عمر دارند) — بنگرید docs/zero-trust/ARCHITECTURE.md.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.core.config import settings

SERVICE_AUTH_HEADER = "X-Internal-Auth"
# مخاطب (aud) توکن‌هایی که به بک‌اند (مسیرهای /api/v1/internal) فرستاده می‌شوند
BACKEND_AUDIENCE = "backend-api"
ALGORITHM = "ES256"
TOKEN_TYPE = "service"
DEFAULT_TTL_SECONDS = 60
MAX_TTL_SECONDS = 300
CLOCK_SKEW_SECONDS = 10


class ServiceAuthError(Exception):
    """توکن سرویس نامعتبر است (دلیل فقط در لاگ؛ پاسخ HTTP همیشه یک 401 کلی)."""


@dataclass(frozen=True)
class ServiceClaims:
    issuer: str
    audience: str
    token_id: str
    expires_at: int
    tenant_id: uuid.UUID | None = None


@lru_cache(maxsize=1)
def _private_key() -> str:
    path = settings.SERVICE_AUTH_PRIVATE_KEY_FILE
    if not path:
        raise ServiceAuthError("SERVICE_AUTH_PRIVATE_KEY_FILE تنظیم نشده است")
    return Path(path).read_text(encoding="ascii")


@lru_cache(maxsize=1)
def _public_keys() -> dict[str, str]:
    directory = settings.SERVICE_AUTH_PUBLIC_KEYS_DIR
    if not directory or not Path(directory).is_dir():
        return {}
    return {path.stem: path.read_text(encoding="ascii") for path in sorted(Path(directory).glob("*.pem"))}


def reset_key_cache() -> None:
    """پس از چرخش کلید (یا در تست‌ها) کلیدها دوباره از فایل خوانده شوند."""
    _private_key.cache_clear()
    _public_keys.cache_clear()


def issue_service_token(
    *,
    audience: str,
    tenant_id: uuid.UUID | str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    issuer: str | None = None,
) -> str:
    """توکن کوتاه‌عمر همین سرویس برای فراخوانی سرویس audience."""
    if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"عمر توکن سرویس باید بین ۱ و {MAX_TTL_SECONDS} ثانیه باشد")
    issuer = issuer or settings.SERVICE_NAME
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": issuer,
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
        "jti": uuid.uuid4().hex,
        "typ": TOKEN_TYPE,
    }
    if tenant_id:
        claims["tid"] = str(tenant_id)
    return jwt.encode(claims, _private_key(), algorithm=ALGORITHM, headers={"kid": issuer})


def verify_service_token(token: str, *, audience: str, allowed_issuers: frozenset[str]) -> ServiceClaims:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as error:
        raise ServiceAuthError(f"ساختار توکن نامعتبر: {error}") from error
    issuer = header.get("kid")
    if header.get("alg") != ALGORITHM:
        raise ServiceAuthError(f"الگوریتم غیرمجاز: {header.get('alg')}")
    if issuer not in allowed_issuers:
        raise ServiceAuthError(f"سرویس {issuer!r} اجازه‌ی فراخوانی این مسیر را ندارد")
    public_key = _public_keys().get(issuer)
    if public_key is None:
        raise ServiceAuthError(f"کلید عمومی سرویس {issuer!r} ثبت نشده است")
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=[ALGORITHM],
            audience=audience,
            issuer=issuer,
            options={
                "require_exp": True,
                "require_iat": True,
                "require_aud": True,
                "require_iss": True,
                "require_jti": True,
                "leeway": CLOCK_SKEW_SECONDS,
            },
        )
    except JWTError as error:
        raise ServiceAuthError(f"امضا یا ادعاهای توکن نامعتبر: {error}") from error
    if claims.get("typ") != TOKEN_TYPE:
        raise ServiceAuthError("توکن از نوع سرویس نیست")
    if claims["exp"] - claims["iat"] > MAX_TTL_SECONDS:
        raise ServiceAuthError("عمر توکن بیش از سقف مجاز است")
    try:
        tenant_id = uuid.UUID(claims["tid"]) if claims.get("tid") else None
    except ValueError as error:
        raise ServiceAuthError("شناسه‌ی سازمان توکن نامعتبر است") from error
    return ServiceClaims(
        issuer=issuer, audience=audience, token_id=claims["jti"], expires_at=claims["exp"], tenant_id=tenant_id
    )


def require_service_token(*allowed_issuers: str, audience: str | None = None):
    """
    Dependency مسیرهای داخلی: بدون هدر X-Internal-Auth، با توکن منقضی، audience اشتباه یا امضای کلید
    ناشناخته ← 401. فقط سرویس‌های allowed_issuers پذیرفته می‌شوند.
    """
    allowed = frozenset(allowed_issuers)

    async def _dependency(request: Request) -> ServiceClaims:
        raw = request.headers.get(SERVICE_AUTH_HEADER, "")
        token = raw.split(" ", 1)[1] if raw.lower().startswith("bearer ") else raw
        if not token:
            raise _unauthorized()
        try:
            return verify_service_token(
                token.strip(), audience=audience or settings.SERVICE_NAME, allowed_issuers=allowed
            )
        except ServiceAuthError as error:
            request.state.service_auth_error = str(error)
            raise _unauthorized() from error

    return _dependency


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="توکن معتبر سرویس داخلی (X-Internal-Auth) ارسال نشده است.",
        headers={"WWW-Authenticate": "ServiceToken"},
    )
