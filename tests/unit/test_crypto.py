"""
تست واحد رمزنگاری داده‌های شخصی (app/core/crypto.py): رفت‌وبرگشت Fernet، کلید اشتباه، چرخش کلید، نوع‌های
ستون SQLAlchemy، ایندکس کور (قطعی، بدون متن خوانا، وابسته به کلید) و توقف برنامه بدون کلید.
"""

import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import settings


@pytest.fixture
def keys(monkeypatch):
    """کلیدهای تازه‌ی همین تست؛ در پایان کش کلیدها پاک می‌شود تا تست‌های دیگر کلید اصلی را ببینند."""
    active, old, index = Fernet.generate_key().decode(), Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "PII_ENCRYPTION_KEYS", active)
    monkeypatch.setattr(settings, "PII_BLIND_INDEX_KEY", index)
    crypto.reset_key_cache()
    yield {"active": active, "old": old, "index": index}
    crypto.reset_key_cache()


def _use(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    crypto.reset_key_cache()


def test_round_trip_produces_unreadable_fernet_ciphertext(keys):
    token = crypto.encrypt_text("09121234567")

    assert token.startswith(crypto.FERNET_PREFIX) and "0912" not in token
    assert crypto.is_encrypted(token)
    assert crypto.decrypt_text(token) == "09121234567"
    assert crypto.encrypt_text("09121234567") != token  # IV تصادفی: دو رمز یک مقدار یکسان نیستند
    assert crypto.encrypt_text(None) is None and crypto.decrypt_text(None) is None


def test_persian_and_unicode_text_survive(keys):
    text = "تهران، خیابان ولیعصر — Senior Python Developer ✓"
    assert crypto.decrypt_text(crypto.encrypt_text(text)) == text


def test_wrong_key_cannot_decrypt(keys, monkeypatch):
    token = crypto.encrypt_text("secret resume text")
    _use(monkeypatch, PII_ENCRYPTION_KEYS=Fernet.generate_key().decode())

    with pytest.raises(crypto.PiiDecryptionError) as error:
        crypto.decrypt_text(token)
    assert "secret" not in str(error.value)


def test_tampered_ciphertext_is_rejected(keys):
    token = crypto.encrypt_text("09121234567")
    tampered = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]

    with pytest.raises(crypto.PiiDecryptionError):
        crypto.decrypt_text(tampered)


def test_key_rotation_old_key_still_decrypts_new_key_encrypts(keys, monkeypatch):
    _use(monkeypatch, PII_ENCRYPTION_KEYS=keys["old"])
    legacy = crypto.encrypt_text("legacy phone")

    _use(monkeypatch, PII_ENCRYPTION_KEYS=f"{keys['active']},{keys['old']}")
    assert crypto.decrypt_text(legacy) == "legacy phone"
    fresh = crypto.encrypt_text("new phone")

    _use(monkeypatch, PII_ENCRYPTION_KEYS=keys["active"])  # کلید قدیمی پس از reencrypt حذف شد
    assert crypto.decrypt_text(fresh) == "new phone"
    with pytest.raises(crypto.PiiDecryptionError):
        crypto.decrypt_text(legacy)


def test_column_types_encrypt_on_write_and_decrypt_on_read(keys):
    text_type, json_type = crypto.EncryptedText(), crypto.EncryptedJSON()
    stored_text = text_type.process_bind_param("Karaj", None)
    stored_json = json_type.process_bind_param({"personal_info": {"phone": "0912"}, "skills": ["Go"]}, None)

    assert crypto.is_encrypted(stored_text) and crypto.is_encrypted(stored_json)
    assert "0912" not in stored_json
    assert text_type.process_result_value(stored_text, None) == "Karaj"
    assert json_type.process_result_value(stored_json, None) == {"personal_info": {"phone": "0912"}, "skills": ["Go"]}
    assert text_type.process_bind_param(None, None) is None and json_type.process_result_value(None, None) is None


def test_blind_index_is_deterministic_and_reveals_no_words(keys):
    tokens = crypto.blind_index_tokens("Python, Django and Node.js — Python")

    assert tokens == crypto.blind_index_tokens("python DJANGO and node js")  # همان کلمات، همان هش‌ها
    assert len(tokens) == 5  # python، django، and، node، js — تکراری‌ها یکی
    assert all(len(token) == crypto.BLIND_INDEX_HEX_LENGTH for token in tokens)
    assert not any(word in "".join(tokens) for word in ("python", "django", "node"))
    assert crypto.blind_index_token("Python") in tokens
    assert crypto.blind_index_tokens(None) is None


def test_blind_index_depends_on_the_secret_key(keys, monkeypatch):
    before = crypto.blind_index_token("python")
    _use(monkeypatch, PII_BLIND_INDEX_KEY=Fernet.generate_key().decode())
    assert crypto.blind_index_token("python") != before  # بدون کلید، فرهنگ‌لغت هش آفلاین ساخته نمی‌شود


@pytest.mark.parametrize(
    "overrides",
    [
        {"PII_ENCRYPTION_KEYS": ""},
        {"PII_ENCRYPTION_KEYS": "not-a-fernet-key"},
        {"PII_BLIND_INDEX_KEY": ""},
        {"PII_BLIND_INDEX_KEY": "c2hvcnQ="},  # کمتر از ۳۲ بایت
    ],
)
def test_missing_or_invalid_keys_stop_startup_without_leaking_them(keys, monkeypatch, overrides):
    _use(monkeypatch, **overrides)

    with pytest.raises(crypto.PiiKeyError) as error:
        crypto.validate_keys()
    for value in overrides.values():
        if value:
            assert value not in str(error.value)
