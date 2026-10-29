"""
تست یکپارچه‌ی حریم خصوصی (GDPR) — معیارهای پذیرش:

1. بازرسی مستقیم دیتابیس (SQL خام، مثل DBeaver): نام، تلفن، آدرس، متن خام و داده‌ی استخراج‌شده‌ی رزومه فقط به
   شکل متن رمزشده‌ی Fernet دیده می‌شوند؛ API همان مقادیر را برای کاربر مجاز باز می‌کند.
2. حذف حساب کارجو (DELETE /api/v1/candidates/me/) حذف فیزیکی نیست: ردیف‌ها می‌مانند، هویت تصادفی/NULL، فایل
   رزومه پاک، نشست‌ها باطل — و خروجی قیف استخدام و روند درخواست‌های داشبورد HR دقیقاً همان قبل است.
3. رضایت‌نامه‌ی پردازش داده هنگام ثبت‌نام کارجو الزامی است و زمانش سمت سرور ثبت می‌شود.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.core.crypto import FERNET_PREFIX
from app.core.privacy import ANONYMIZED_FIRST_NAME, PRIVACY_NOTICE_VERSION
from app.core.storage import resolve_local_media_path
from app.models import Application, Candidate, Resume, StatusHistory, User
from tests.integration.conftest import TEST_PASSWORD, auth_headers

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PROFILE = {"first_name": "Sara", "last_name": "Ahmadi", "phone": "09121234567", "location": "Tehran, Vanak"}
RESUME_TEXT = "Sara Ahmadi 09121234567 sara.ahmadi@mail.test — Senior Python and Django developer, Kubernetes"
PARSED = {"personal_info": {"name": "Sara Ahmadi", "phone": "09121234567"}, "education": [], "work_experience": []}


async def _raw(db_session, sql: str, **params) -> dict:
    """خواندن ردیف مثل یک کلاینت دیتابیس (بدون نوع‌های ORM و بدون رمزگشایی)."""
    return dict((await db_session.execute(text(sql), params)).mappings().one())


async def _candidate_with_resume(client, db_session, make_application):
    """کارجو با پروفایل کامل، یک رزومه‌ی آپلودشده (فایل واقعی روی دیسک) و متن/داده‌ی استخراج‌شده."""
    _, _, job = await make_application()
    application, candidate_user, _ = await make_application(job=job, status="Applied", score_ai=81)
    headers = auth_headers(candidate_user)
    assert (await client.put("/api/v1/candidates/me", json=PROFILE, headers=headers)).status_code == 200

    upload = await client.post(
        "/api/v1/resumes/upload",
        data={"job_id": str(job.id)},
        files={"file": ("Sara_Ahmadi_CV.pdf", MINIMAL_PDF, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code in (202, 409), upload.text  # 409: همین کارجو قبلاً برای این آگهی درخواست داده
    resume = (
        await db_session.execute(select(Resume).where(Resume.candidate_id == application.candidate_id))
    ).scalar_one()
    resume.raw_text = RESUME_TEXT  # همان کاری که Worker پردازش رزومه انجام می‌دهد
    resume.parsed_data = PARSED
    resume.skill_analysis = {
        "skills": ["Python", "Django"],
        "total_experience_years": 6.0,
        "experience_entries": [{"company": "Acme Corp", "title": "Backend Lead", "start": "2018-01"}],
    }
    await db_session.commit()
    return application, candidate_user, job, resume


async def test_pii_is_ciphertext_in_the_database_and_plaintext_through_the_api(
    client, db_session, make_application, make_user
):
    application, candidate_user, _, resume = await _candidate_with_resume(client, db_session, make_application)

    candidate_row = await _raw(
        db_session,
        "SELECT first_name, last_name, phone, location FROM candidates WHERE id = :id",
        id=application.candidate_id,
    )
    resume_row = await _raw(
        db_session, "SELECT raw_text, parsed_data, search_tokens FROM resumes WHERE id = :id", id=resume.id
    )
    for column, value in {
        **candidate_row,
        "raw_text": resume_row["raw_text"],
        "parsed_data": resume_row["parsed_data"],
    }.items():
        assert value.startswith(FERNET_PREFIX), column
    stored = " ".join(
        [*candidate_row.values(), resume_row["raw_text"], resume_row["parsed_data"], *resume_row["search_tokens"]]
    )
    for secret in ("Sara", "Ahmadi", "0912", "Tehran", "Vanak", "Python", "Kubernetes", "sara.ahmadi"):
        assert secret.lower() not in stored.lower(), secret

    # کاربر مجاز همان مقادیر خوانا را می‌بیند (رمزگشایی خودکار در SQLAlchemy)
    me = (await client.get("/api/v1/candidates/me", headers=auth_headers(candidate_user))).json()
    assert {key: me[key] for key in PROFILE} == PROFILE
    hr_headers = auth_headers(await make_user(role="HR_Manager"))
    found = (
        await client.get("/api/v1/candidates/search/", params={"q": "python AND kubernetes"}, headers=hr_headers)
    ).json()
    item = next(item for item in found["items"] if item["candidate_id"] == str(application.candidate_id))
    assert (item["phone"], item["location"], item["last_name"]) == ("09121234567", "Tehran, Vanak", "Ahmadi")
    detail = (await client.get(f"/api/v1/resumes/{resume.id}", headers=hr_headers)).json()
    assert detail["parsed_data"]["personal_info"]["phone"] == "09121234567"


async def test_resume_search_works_on_the_blind_index(client, db_session, make_application, make_user):
    application, _, _, _ = await _candidate_with_resume(client, db_session, make_application)
    hr_headers = auth_headers(await make_user(role="HR_Manager"))

    async def search(q: str) -> bool:
        response = await client.get("/api/v1/candidates/search/", params={"q": q}, headers=hr_headers)
        assert response.status_code == 200
        return str(application.candidate_id) in [item["candidate_id"] for item in response.json()["items"]]

    assert await search("Python AND Django")
    assert await search("rust OR KUBERNETES")
    assert await search("django")
    assert not await search("Python AND Rust")
    assert not await search("Pyth")  # فقط کلمه‌ی کامل (محدودیت مستندشده‌ی ایندکس کور)


async def _dashboard(client, headers) -> tuple[dict, list]:
    funnel = await client.get("/api/v1/analytics/funnel", headers=headers)
    trend = await client.get("/api/v1/analytics/applications-trend", params={"days": 30}, headers=headers)
    assert funnel.status_code == 200 and trend.status_code == 200
    return funnel.json(), trend.json()


async def test_delete_account_anonymizes_without_breaking_hr_statistics(
    client, db_session, make_application, make_user, fake_redis
):
    application, candidate_user, job, resume = await _candidate_with_resume(client, db_session, make_application)
    await make_application(job=job, status="Screening", score_ai=70)  # کارجوی دیگری در همان قیف
    db_session.add(
        StatusHistory(
            application_id=application.id,
            tenant_id=application.tenant_id,
            old_status="Draft",
            new_status="Applied",
            changed_by=candidate_user.id,
        )
    )
    await db_session.commit()
    file_path = resolve_local_media_path(resume.file_url)
    assert file_path is not None and file_path.is_file()
    hr_headers = auth_headers(await make_user(role="HR_Manager", tenant=None))
    candidate_headers = auth_headers(candidate_user)
    before = await _dashboard(client, hr_headers)
    counts_before = await _row_counts(db_session)

    # شناسه‌ها پیش از درخواست (اشیای ORM بعد از expire_all دیگر بدون I/O خوانده نمی‌شوند)
    ids = {
        "candidate": application.candidate_id,
        "user": candidate_user.id,
        "resume": resume.id,
        "application": application.id,
    }
    old_email, old_password_hash = candidate_user.email, candidate_user.password_hash

    response = await client.delete("/api/v1/candidates/me/", headers=candidate_headers)
    assert response.status_code == 200  # مسیر دقیق با «/» پایانی؛ بدون Redirect
    assert response.json()["resumes_cleared"] == 1 and response.json()["files_deleted"] == 1

    # آمار داشبورد HR و تعداد ردیف‌ها دقیقاً همان قبل (Hard Delete نیست)
    assert await _dashboard(client, hr_headers) == before
    assert await _row_counts(db_session) == counts_before

    db_session.expire_all()
    candidate = await db_session.get(Candidate, ids["candidate"])
    assert candidate.first_name == ANONYMIZED_FIRST_NAME and candidate.last_name.startswith("#")
    assert (candidate.phone, candidate.location, candidate.skills) == (None, None, None)
    user = await db_session.get(User, ids["user"])
    assert user.email.startswith("deleted-") and user.email.endswith("@anonymized.invalid")
    assert not user.is_active and user.anonymized_at is not None
    assert user.password_hash != old_password_hash
    stored_resume = await db_session.get(Resume, ids["resume"])
    assert (stored_resume.raw_text, stored_resume.parsed_data, stored_resume.search_tokens) == (None, None, None)
    assert stored_resume.file_url == f"deleted:{ids['resume']}"
    assert stored_resume.skill_analysis == {"skills": ["Python", "Django"], "total_experience_years": 6.0}
    assert not file_path.exists()
    stored_application = await db_session.get(Application, ids["application"])
    assert (stored_application.current_status, stored_application.score_ai) == ("Applied", 81)

    # هیچ اثری از هویت قبلی در دیتابیس نمانده، حتی به شکل رمزشده
    raw = await _raw(
        db_session, "SELECT first_name, last_name, phone FROM candidates WHERE id = :id", id=ids["candidate"]
    )
    assert raw["phone"] is None and raw["first_name"].startswith(FERNET_PREFIX)
    assert (await db_session.execute(select(User).where(User.email == old_email))).first() is None

    # نشست‌ها باطل: همان توکن ← 401 (درخواست دوم حذف هم)، و جستجوی HR دیگر او را با کلمات رزومه پیدا نمی‌کند
    assert (await client.get("/api/v1/candidates/me", headers=candidate_headers)).status_code == 401
    assert (await client.delete("/api/v1/candidates/me/", headers=candidate_headers)).status_code == 401
    assert not fake_redis.keys(f"user_sessions:{ids['user']}")
    found = (await client.get("/api/v1/candidates/search/", params={"q": "kubernetes"}, headers=hr_headers)).json()
    assert str(ids["candidate"]) not in [item["candidate_id"] for item in found["items"]]
    login = await client.post("/api/v1/auth/login", json={"email": old_email, "password": TEST_PASSWORD})
    assert login.status_code == 401


async def _row_counts(db_session) -> dict:
    counts = {}
    for table in ("users", "candidates", "applications", "resumes", "status_history"):
        counts[table] = (await db_session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    return counts


async def test_only_candidates_can_delete_their_own_account(client, make_user):
    for role in ("HR_Manager", "Admin"):
        response = await client.delete("/api/v1/candidates/me/", headers=auth_headers(await make_user(role=role)))
        assert response.status_code == 403
    assert (await client.delete("/api/v1/candidates/me/")).status_code == 401


async def test_account_without_profile_or_resume_is_anonymized(client, db_session, make_user):
    user = await make_user(role="Candidate")
    user_id = user.id
    response = await client.delete("/api/v1/candidates/me/", headers=auth_headers(user))
    assert response.status_code == 200 and response.json()["resumes_cleared"] == 0
    db_session.expire_all()
    assert (await db_session.get(User, user_id)).anonymized_at is not None


async def test_candidate_registration_requires_and_records_data_consent(client, db_session):
    base = {"email": "consent@example.com", "password": TEST_PASSWORD, "role": "Candidate"}

    for body in (base, {**base, "data_consent": False}):
        response = await client.post("/api/v1/auth/register", json=body)
        assert response.status_code == 422
        assert "data_consent" in response.text

    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    # زمان ارسالی کلاینت پذیرفته نمی‌شود؛ زمان رضایت را سرور ثبت می‌کند
    response = await client.post(
        "/api/v1/auth/register", json={**base, "data_consent": True, "data_consent_at": "2001-01-01T00:00:00Z"}
    )
    assert response.status_code == 201
    user = (await db_session.execute(select(User).where(User.email == base["email"]))).scalar_one()
    assert user.data_consent_at >= started and user.data_consent_version == PRIVACY_NOTICE_VERSION


async def test_admin_registration_does_not_require_candidate_consent(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"admin-{uuid.uuid4().hex[:6]}@example.com",
            "password": TEST_PASSWORD,
            "role": "Admin",
            "company_name": "Consent Org",
        },
    )
    assert response.status_code == 201


class _SharedSession:
    """AsyncSessionLocal() جایگزین: همان Session تراکنشی تست (در پایان بسته نمی‌شود)."""

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


async def test_plaintext_left_by_a_rolling_update_is_readable_then_encrypted(
    client, db_session, make_application, monkeypatch
):
    """کانتینر نسخه‌ی قبلی در چند دقیقه‌ی Rolling Update ممکن است متن خوانا بنویسد: خواندنش خطا نمی‌دهد و
    deploy.sh با «python -m app.core.crypto encrypt-legacy» فقط همان ردیف‌ها را رمز می‌کند."""
    from app.core import crypto
    from app.db import session as session_module

    application, candidate_user, _ = await make_application(status="Applied")
    candidate_id = application.candidate_id
    await db_session.execute(
        text("UPDATE candidates SET phone = '09120000000', location = 'Qom' WHERE id = :id"), {"id": candidate_id}
    )
    await db_session.commit()

    me = await client.get("/api/v1/candidates/me", headers=auth_headers(candidate_user))
    assert me.status_code == 200 and (me.json()["phone"], me.json()["location"]) == ("09120000000", "Qom")

    monkeypatch.setattr(session_module, "AsyncSessionLocal", _SharedSession(db_session))
    counts = await crypto._reencrypt(only_legacy=True)
    assert counts["candidates"] >= 1
    row = await _raw(db_session, "SELECT phone, location FROM candidates WHERE id = :id", id=candidate_id)
    assert row["phone"].startswith(FERNET_PREFIX) and row["location"].startswith(FERNET_PREFIX)
    assert (await crypto._reencrypt(only_legacy=True)) == {"candidates": 0, "resumes": 0}  # دیگر چیزی نمانده


async def test_sessions_are_revoked_even_if_file_storage_fails(client, db_session, make_application, monkeypatch):
    """
    یافته‌ی Production: Volume رزومه‌ها مجوز نوشتن نداشت و ساخت بک‌اند ذخیره‌سازی PermissionError می‌داد؛ پاسخ
    500 بود و نشست‌ها باطل نمی‌شدند. حالا ابطال نشست‌ها اولین گام بعد از commit است و خطای فایل ناشناس‌سازی را
    نمی‌شکند.
    """
    from app.core import privacy

    _, candidate_user, _, resume = await _candidate_with_resume(client, db_session, make_application)
    headers = auth_headers(candidate_user)

    def broken_storage():
        raise PermissionError("[Errno 13] Permission denied: '/app/media/resumes'")

    monkeypatch.setattr(privacy, "get_storage_backend", broken_storage)
    response = await client.delete("/api/v1/candidates/me/", headers=headers)

    assert response.status_code == 200 and response.json()["files_deleted"] == 0
    assert (await client.get("/api/v1/candidates/me", headers=headers)).status_code == 401
