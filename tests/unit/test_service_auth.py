"""تست واحد توکن سرویس‌به‌سرویس (app/core/service_auth.py): صدور، اعتبارسنجی و حمله‌های رایج."""

import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwt

from app.core import service_auth
from app.core.config import settings
from app.core.service_auth import ServiceAuthError, issue_service_token, verify_service_token

ALLOWED = frozenset({"worker"})


def _keypair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """کلید سرویس worker (فرستنده) + پوشه‌ی کلیدهای عمومی گیرنده؛ یک کلید بیگانه‌ی ثبت‌نشده هم ساخته می‌شود."""
    worker_private, worker_public = _keypair()
    rogue_private, _ = _keypair()
    (tmp_path / "worker.key").write_text(worker_private)
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    (public_dir / "worker.pem").write_text(worker_public)
    monkeypatch.setattr(settings, "SERVICE_NAME", "worker")
    monkeypatch.setattr(settings, "SERVICE_AUTH_PRIVATE_KEY_FILE", str(tmp_path / "worker.key"))
    monkeypatch.setattr(settings, "SERVICE_AUTH_PUBLIC_KEYS_DIR", str(public_dir))
    service_auth.reset_key_cache()
    yield {"worker": worker_private, "rogue": rogue_private}
    service_auth.reset_key_cache()


def _signed(private_key: str, *, kid: str = "worker", algorithm: str = "ES256", **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "worker",
        "sub": "worker",
        "aud": "backend-api",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "jti": uuid.uuid4().hex,
        "typ": "service",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm=algorithm, headers={"kid": kid})


def _verify(token: str, audience: str = "backend-api"):
    return verify_service_token(token, audience=audience, allowed_issuers=ALLOWED)


def test_issued_token_round_trips_with_short_lifetime_and_tenant(keys):
    tenant_id = uuid.uuid4()
    token = issue_service_token(audience="backend-api", tenant_id=tenant_id)

    claims = _verify(token)

    assert claims.issuer == "worker" and claims.audience == "backend-api" and claims.tenant_id == tenant_id
    assert 0 < claims.expires_at - time.time() <= 60
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256" and header["kid"] == "worker"
    assert issue_service_token(audience="backend-api") != issue_service_token(audience="backend-api")  # jti یکتا


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "wrong_audience",
        "unknown_key",
        "unregistered_service",
        "long_lived",
        "not_service_type",
        "missing_jti",
    ],
)
def test_invalid_tokens_are_rejected(keys, case):
    now = int(time.time())
    token = {
        "expired": lambda: _signed(keys["worker"], iat=now - 600, nbf=now - 600, exp=now - 300),
        "wrong_audience": lambda: _signed(keys["worker"], aud="other-service"),
        # امضا با کلیدی که گیرنده نمی‌شناسد ولی با ادعای هویت worker (جعل هویت)
        "unknown_key": lambda: _signed(keys["rogue"]),
        "unregistered_service": lambda: _signed(keys["rogue"], kid="genai-worker", iss="genai-worker"),
        "long_lived": lambda: _signed(keys["worker"], exp=now + 3600),
        "not_service_type": lambda: _signed(keys["worker"], typ="access"),
        "missing_jti": lambda: _signed(keys["worker"], jti=None),
    }[case]()

    with pytest.raises(ServiceAuthError):
        _verify(token)


def test_tampered_payload_and_algorithm_confusion_are_rejected(keys):
    token = issue_service_token(audience="backend-api", tenant_id=uuid.uuid4())
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["tid"] = str(uuid.uuid4())  # تغییر سازمان بعد از امضا
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    with pytest.raises(ServiceAuthError):
        _verify(f"{header}.{forged_payload}.{signature}")
    # HS256 با کلید عمومی (که همه می‌دانند) به‌عنوان راز مشترک — حمله‌ی کلاسیک Algorithm Confusion؛
    # توکن دستی ساخته می‌شود چون خود کتابخانه امضای HMAC با کلید نامتقارن را هم رد می‌کند
    public_key = service_auth._public_keys()["worker"].encode()
    forged_header = base64.urlsafe_b64encode(b'{"alg":"HS256","kid":"worker","typ":"JWT"}').rstrip(b"=")
    signing_input = forged_header + b"." + payload.encode()
    mac = base64.urlsafe_b64encode(hmac.new(public_key, signing_input, hashlib.sha256).digest()).rstrip(b"=")
    with pytest.raises(ServiceAuthError):
        _verify((signing_input + b"." + mac).decode())
    with pytest.raises(ServiceAuthError):
        _verify("not-a-jwt")


def test_issue_requires_key_and_bounded_ttl(keys, monkeypatch):
    with pytest.raises(ValueError):
        issue_service_token(audience="backend-api", ttl_seconds=301)
    monkeypatch.setattr(settings, "SERVICE_AUTH_PRIVATE_KEY_FILE", "")
    service_auth.reset_key_cache()
    with pytest.raises(ServiceAuthError):
        issue_service_token(audience="backend-api")
