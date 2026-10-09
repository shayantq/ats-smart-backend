"""
تست یکپارچه‌سازی احراز هویت: ثبت‌نام/ورود/بازیابی رمز از طریق API و بررسی جدول users.
"""

import asyncio

from sqlalchemy import select

from app.core.security import decode_token, verify_password
from app.models import User
from tests.integration.conftest import TEST_PASSWORD, auth_headers

NEW_USER = {"email": "new.user@example.com", "password": "Str0ngPass!", "role": "Candidate"}


async def test_register_persists_user_with_bcrypt_hash(client, db_session):
    response = await client.post("/api/v1/auth/register", json=NEW_USER)

    assert response.status_code == 201
    user = (await db_session.execute(select(User).where(User.email == NEW_USER["email"]))).scalar_one()
    assert user.role == "Candidate"
    # گذرواژه هرگز خام ذخیره نمی‌شود
    assert user.password_hash != NEW_USER["password"]
    assert user.password_hash.startswith("$2")  # فرمت Bcrypt
    assert verify_password(NEW_USER["password"], user.password_hash)


async def test_register_duplicate_email_returns_400(client):
    await client.post("/api/v1/auth/register", json=NEW_USER)

    response = await client.post("/api/v1/auth/register", json=NEW_USER)

    assert response.status_code == 400


async def test_register_rejects_short_password(client):
    response = await client.post("/api/v1/auth/register", json={**NEW_USER, "password": "short"})

    assert response.status_code == 422


async def test_login_returns_access_and_refresh_tokens(client, make_user):
    user = await make_user(role="HR_Manager")

    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert decode_token(body["access_token"]) | {} and decode_token(body["access_token"])["type"] == "access"
    assert decode_token(body["refresh_token"])["type"] == "refresh"
    assert decode_token(body["access_token"])["sub"] == str(user.id)
    assert "refresh_token" in response.cookies


async def test_login_with_wrong_password_returns_401(client, make_user):
    user = await make_user()

    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"})

    assert response.status_code == 401


async def test_protected_route_rejects_wrong_role_and_missing_token(client, make_user):
    hr_manager = await make_user(role="HR_Manager")
    admin = await make_user(role="Admin")

    assert (await client.get("/api/v1/admin/stats")).status_code == 401
    assert (await client.get("/api/v1/admin/stats", headers=auth_headers(hr_manager))).status_code == 403
    stats = await client.get("/api/v1/admin/stats", headers=auth_headers(admin))
    assert stats.status_code == 200
    assert stats.json()["total_users"] == 2


async def test_password_reset_with_otp_end_to_end(client, db_session, make_user, fake_cache, enqueued_tasks):
    user = await make_user()

    response = await client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert response.status_code == 200

    # کد OTP در پس‌زمینه (asyncio.create_task) تولید و ذخیره می‌شود — منتظر اجرای آن می‌مانیم
    cache_key = f"password_reset_otp:{user.email}"
    for _ in range(50):
        if cache_key in fake_cache.store:
            break
        await asyncio.sleep(0.01)
    otp_code = fake_cache.store[cache_key]["otp"]
    assert [name for name, _ in enqueued_tasks] == ["send_otp_email_task"]

    reset = await client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp_code": otp_code, "new_password": "BrandNewPass1"},
    )
    assert reset.status_code == 200

    await db_session.refresh(user)
    assert verify_password("BrandNewPass1", user.password_hash)
    # OTP یک‌بارمصرف است
    reused = await client.post(
        "/api/v1/auth/reset-password",
        json={"email": user.email, "otp_code": otp_code, "new_password": "AnotherPass1"},
    )
    assert reused.status_code == 400


async def test_forgot_password_for_unknown_email_gives_same_response(client, enqueued_tasks):
    response = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})

    assert response.status_code == 200  # همان پاسخ همیشگی — جلوگیری از User Enumeration
    await asyncio.sleep(0.05)
    assert enqueued_tasks == []
