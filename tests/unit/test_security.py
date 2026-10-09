"""تست واحد ابزارهای امنیتی: هش گذرواژه، توکن‌های JWT (security.py) و پاکسازی XSS (sanitize.py)."""

from datetime import timedelta

import pytest
from jose import JWTError, jwt

from app.core.config import settings
from app.core.sanitize import strip_html_tags
from app.core.security import (
    JWT_ALGORITHM,
    _create_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_is_salted_bcrypt_and_verifiable():
    first, second = hash_password("S3cret!pass"), hash_password("S3cret!pass")

    assert first != "S3cret!pass"
    assert first.startswith("$2")  # Bcrypt
    assert first != second  # Salt تصادفی — دو هش یکسان نیستند
    assert verify_password("S3cret!pass", first)
    assert not verify_password("wrong-pass", first)


def test_access_and_refresh_tokens_carry_subject_type_and_lifetime():
    access_token, access_ttl = create_access_token("user-123")
    refresh_token, refresh_ttl = create_refresh_token("user-123")

    assert decode_token(access_token)["sub"] == "user-123"
    assert decode_token(access_token)["type"] == "access"
    assert decode_token(refresh_token)["type"] == "refresh"
    assert access_ttl == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert refresh_ttl == settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600


def test_expired_token_is_rejected():
    expired_token, _ = _create_token("user-123", timedelta(seconds=-1), token_type="access")

    with pytest.raises(JWTError):
        decode_token(expired_token)


def test_token_signed_with_another_key_is_rejected():
    forged = jwt.encode({"sub": "admin", "type": "access"}, "attacker-key", algorithm=JWT_ALGORITHM)

    with pytest.raises(JWTError):
        decode_token(forged)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("<script>alert(1)</script>Ali", "alert(1)Ali"),
        ('<img src=x onerror="hack()">Sara', "Sara"),
        ("  plain text  ", "plain text"),
    ],
)
def test_html_tags_are_stripped(raw, clean):
    assert strip_html_tags(raw) == clean


def test_non_string_values_pass_through():
    assert strip_html_tags(None) is None
    assert strip_html_tags(42) == 42
