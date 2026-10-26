"""
تست یکپارچه‌ی چندمستاجری (Multi-Tenancy) — دو سازمان واقعی روی همان دیتابیس:

- معیار ۱: هر GET (لیست کارجویان، آگهی‌ها، درخواست‌ها) خودکار فقط داده‌ی سازمان کاربر لاگین‌شده را
  برمی‌گرداند، بدون ارسال شناسه‌ی سازمان در درخواست.
- معیار ۲: HR سازمان دیگر با شناسه‌ی مستقیم رزومه/درخواست/آگهی → 404 (نه 403؛ وجود رکورد افشا نمی‌شود).
- دفاع در عمق: حتی کوئری خام SQL (بدون فیلتر ORM — شبیه‌سازی باگ بک‌اند) زیر نقش ats_app فقط ردیف‌های
  همان سازمان را می‌بیند؛ و با خاموش کردن RLS، فیلتر خودکار TenantMixin به‌تنهایی هم همین را تضمین می‌کند.
"""

import uuid

import pytest
from sqlalchemy import select, text

from app.core import tenancy
from app.core.config import settings
from app.core.security import create_access_token
from app.core.tenancy import SCOPE_TENANT, TenantContext, TenantAccessError, use_tenant_context
from app.models import Application, Candidate, Job, Resume, User
from tests.integration.conftest import TEST_PASSWORD, auth_headers


@pytest.fixture
async def two_orgs(db_session, make_tenant, make_user):
    """سازمان A و B، هر کدام یک HR، یک آگهی، و یک کارجوی متقاضی با رزومه."""
    orgs = {}
    for label in ("A", "B"):
        company, owner = await make_tenant(f"Org {label}")
        hr = await make_user(role="HR_Manager", tenant=company)
        job = Job(title=f"Job {label}", skills_required=["Python"], created_by=hr.id, tenant_id=company.id)
        candidate_user = await make_user(role="Candidate")
        candidate = Candidate(user_id=candidate_user.id, first_name=f"Cand{label}", last_name="X")
        db_session.add_all([job, candidate])
        await db_session.flush()
        application = Application(
            job_id=job.id, candidate_id=candidate.id, tenant_id=company.id, current_status="Applied"
        )
        resume = Resume(
            candidate_id=candidate.id,
            tenant_id=company.id,
            file_url=f"http://test/media/{label}.pdf",
            raw_text="Python developer",
            skill_analysis={"skills": ["Python"], "total_experience_years": 4.0},
        )
        db_session.add_all([application, resume])
        await db_session.commit()
        orgs[label] = {
            "company": company,
            "owner": owner,
            "hr": hr,
            "job": job,
            "candidate": candidate,
            "candidate_user": candidate_user,
            "application": application,
            "resume": resume,
        }
    return orgs


async def test_list_endpoints_return_only_own_tenant_data_without_tenant_parameter(client, two_orgs):
    for label, other in (("A", "B"), ("B", "A")):
        headers = auth_headers(two_orgs[label]["hr"])

        candidates = (await client.get("/api/v1/candidates/search/", headers=headers)).json()["items"]
        assert [item["candidate_id"] for item in candidates] == [str(two_orgs[label]["candidate"].id)]

        jobs = (await client.get("/api/v1/jobs/", headers=headers)).json()["items"]
        assert [job["title"] for job in jobs] == [f"Job {label}"]

        board = await client.get(
            "/api/v1/applications/", params={"job_id": str(two_orgs[label]["job"].id)}, headers=headers
        )
        assert [item["application_id"] for item in board.json()["items"]] == [str(two_orgs[label]["application"].id)]
        foreign_board = await client.get(
            "/api/v1/applications/", params={"job_id": str(two_orgs[other]["job"].id)}, headers=headers
        )
        assert foreign_board.status_code == 404 or foreign_board.json()["items"] == []


async def test_direct_access_to_other_tenant_record_returns_404(client, db_session, two_orgs):
    hr_b = auth_headers(two_orgs["B"]["hr"])
    resume_a, application_a, job_a = two_orgs["A"]["resume"], two_orgs["A"]["application"], two_orgs["A"]["job"]

    own = await client.get(f"/api/v1/resumes/{resume_a.id}", headers=auth_headers(two_orgs["A"]["hr"]))
    assert own.status_code == 200 and own.json()["tenant_id"] == str(two_orgs["A"]["company"].id)

    foreign = await client.get(f"/api/v1/resumes/{resume_a.id}", headers=hr_b)
    missing = await client.get(f"/api/v1/resumes/{uuid.uuid4()}", headers=hr_b)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()  # «مال سازمان دیگر» از «وجود ندارد» قابل تشخیص نیست

    status_change = await client.put(
        f"/api/v1/applications/{application_a.id}/status",
        json={"current_status": "Applied", "new_status": "Screening"},
        headers=hr_b,
    )
    assert status_change.status_code == 404
    assert (await client.delete(f"/api/v1/jobs/{job_a.id}", headers=hr_b)).status_code == 404

    await db_session.refresh(job_a)
    await db_session.refresh(application_a)
    assert job_a.status == "Active" and application_a.current_status == "Applied"


async def _raw_rows(db_session, context: TenantContext, sql: str, **params) -> list:
    await db_session.commit()  # تراکنش تازه → after_begin نقش و متغیرهای RLS همین Context را اعمال می‌کند
    with use_tenant_context(context):
        rows = (await db_session.execute(text(sql), params)).all()
        await db_session.rollback()
    return rows


def _ids(two_orgs) -> dict:
    """شناسه‌ها پیش از هر rollback (که اشیای Session را منقضی می‌کند) خوانده می‌شوند."""
    return {
        f"{key}_{label}": two_orgs[label][key].id
        for label in ("A", "B")
        for key in ("company", "hr", "job", "candidate", "resume", "application")
    }


def _context(ids: dict, label: str) -> TenantContext:
    return TenantContext(SCOPE_TENANT, tenant_id=ids[f"company_{label}"], user_id=ids[f"hr_{label}"])


async def test_rls_blocks_raw_sql_even_without_orm_filter(db_session, two_orgs):
    """کوئری خام هیچ شرط tenant_id ندارد (مثل باگی که فیلتر را فراموش کرده) — خود PostgreSQL ردیف‌ها را حذف می‌کند."""
    ids = _ids(two_orgs)
    context_b = _context(ids, "B")

    assert await _raw_rows(db_session, context_b, "SELECT id FROM resumes WHERE id = :id", id=ids["resume_A"]) == []
    assert [row.id for row in await _raw_rows(db_session, context_b, "SELECT id FROM resumes")] == [ids["resume_B"]]
    candidates = await _raw_rows(db_session, context_b, "SELECT id FROM candidates")
    assert [row.id for row in candidates] == [ids["candidate_B"]]
    hijack = "UPDATE jobs SET title = 'x' WHERE id = :id RETURNING id"
    assert await _raw_rows(db_session, context_b, hijack, id=ids["job_A"]) == []
    assert (await _raw_rows(db_session, context_b, "SELECT current_user"))[0][0] == settings.DB_RLS_ROLE

    # بدون Context سازمان (مثلاً Middleware توکن را نخواند)، نقش ats_app هیچ داده‌ی عملیاتی نمی‌بیند (Fail-Closed)
    nobody = TenantContext("public")
    assert await _raw_rows(db_session, nobody, "SELECT id FROM resumes") == []
    assert await _raw_rows(db_session, nobody, "SELECT id FROM applications") == []


async def test_cross_tenant_insert_is_rejected_by_database(db_session, two_orgs):
    ids = _ids(two_orgs)
    await db_session.commit()
    with use_tenant_context(_context(ids, "B")):
        with pytest.raises(Exception, match="row-level security"):
            await db_session.execute(
                text(
                    "INSERT INTO jobs (id, title, status, created_by, tenant_id) "
                    "VALUES (gen_random_uuid(), 'Injected', 'Active', :creator, :tenant)"
                ),
                {"creator": ids["hr_B"], "tenant": ids["company_A"]},
            )
        await db_session.rollback()
        # لایه‌ی ORM حتی پیش از رسیدن به دیتابیس جلوی نوشتن ردیف با tenant دیگر را می‌گیرد
        db_session.add(Job(title="Injected", created_by=ids["hr_B"], tenant_id=ids["company_A"]))
        with pytest.raises(TenantAccessError):
            await db_session.flush()
        await db_session.rollback()


async def test_orm_mixin_filters_on_its_own_when_rls_is_bypassed(db_session, two_orgs, monkeypatch):
    """لایه‌ی دوم مستقل: نقش اصلی اتصال (معاف از RLS) + Context سازمان B → فقط فیلتر خودکار ORM عمل می‌کند."""
    ids = _ids(two_orgs)
    monkeypatch.setattr(settings, "DB_RLS_ROLE", "none")
    await db_session.commit()
    with use_tenant_context(_context(ids, "B")):
        assert (await db_session.execute(text("SELECT count(*) FROM resumes"))).scalar_one() == 2  # RLS خاموش
        resumes = (await db_session.execute(select(Resume.id))).scalars().all()
        assert resumes == [ids["resume_B"]]
        assert (await db_session.execute(select(Resume.id).where(Resume.id == ids["resume_A"]))).first() is None
        await db_session.rollback()


async def test_candidate_applies_to_two_orgs_each_sees_only_its_application(client, db_session, two_orgs):
    """کارجو موجودیت سراسری است: درخواست‌هایش به هر دو سازمان را می‌بیند، ولی هر سازمان فقط درخواست خودش را."""
    candidate_user = two_orgs["A"]["candidate_user"]
    candidate = two_orgs["A"]["candidate"]
    db_session.add(
        Application(
            job_id=two_orgs["B"]["job"].id,
            candidate_id=candidate.id,
            tenant_id=two_orgs["B"]["company"].id,
            current_status="Applied",
        )
    )
    await db_session.commit()

    mine = (await client.get("/api/v1/candidates/me/applications", headers=auth_headers(candidate_user))).json()
    assert len(mine["items"]) == 2

    for label in ("A", "B"):
        found = (await client.get("/api/v1/candidates/search/", headers=auth_headers(two_orgs[label]["hr"]))).json()
        assert str(candidate.id) in [item["candidate_id"] for item in found["items"]]
    # کارجوی B فقط به سازمان B درخواست داده؛ سازمان A او را نمی‌بیند
    found_a = (await client.get("/api/v1/candidates/search/", headers=auth_headers(two_orgs["A"]["hr"]))).json()
    assert str(two_orgs["B"]["candidate"].id) not in [item["candidate_id"] for item in found_a["items"]]


async def test_token_tenant_must_match_user_tenant(client, two_orgs):
    hr_a = two_orgs["A"]["hr"]
    legacy_token, _ = create_access_token(str(hr_a.id))  # توکن قدیمی بدون tid
    forged_token, _ = create_access_token(str(hr_a.id), tenant_id=two_orgs["B"]["company"].id)
    for token in (legacy_token, forged_token):
        response = await client.get("/api/v1/jobs/", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200  # مسیر عمومی؛ ولی…
        assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401
        assert (
            await client.get(
                f"/api/v1/resumes/{two_orgs['B']['resume'].id}", headers={"Authorization": f"Bearer {token}"}
            )
        ).status_code == 401


async def test_admin_onboarding_creates_isolated_tenant(client, db_session):
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "founder@neworg.com", "password": TEST_PASSWORD, "role": "Admin", "company_name": "New Org"},
    )
    assert register.status_code == 201
    tenant_id = register.json()["data"]["tenant_id"]
    assert tenant_id is not None

    hr_signup = await client.post(
        "/api/v1/auth/register", json={"email": "hr@neworg.com", "password": TEST_PASSWORD, "role": "HR_Manager"}
    )
    assert hr_signup.status_code == 422  # کارمند ثبت‌نام عمومی ندارد
    assert (
        await client.post(
            "/api/v1/auth/register", json={"email": "a2@neworg.com", "password": TEST_PASSWORD, "role": "Admin"}
        )
    ).status_code == 422

    login = await client.post("/api/v1/auth/login", json={"email": "founder@neworg.com", "password": TEST_PASSWORD})
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/v1/tenant", headers=admin_headers)).json()["name"] == "New Org"

    created = await client.post(
        "/api/v1/tenant/users",
        json={"email": "hr@neworg.com", "password": TEST_PASSWORD, "role": "HR_Manager"},
        headers=admin_headers,
    )
    assert created.status_code == 201 and created.json()["tenant_id"] == tenant_id

    hr_login = await client.post("/api/v1/auth/login", json={"email": "hr@neworg.com", "password": TEST_PASSWORD})
    hr_headers = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}
    job = await client.post(
        "/api/v1/jobs/", json={"title": "First role", "skills_required": ["Go"]}, headers=hr_headers
    )
    assert job.status_code == 201

    stored = (await db_session.execute(select(Job).where(Job.id == uuid.UUID(job.json()["job_id"])))).scalar_one()
    assert str(stored.tenant_id) == tenant_id  # tenant_id خودکار از Context، بدون ارسال در بدنه‌ی درخواست
    members = (await client.get("/api/v1/tenant/users", headers=admin_headers)).json()["items"]
    assert {member["email"] for member in members} == {"founder@neworg.com", "hr@neworg.com"}
    assert (await client.get("/api/v1/tenant/users", headers=hr_headers)).status_code == 403
    founder = (await db_session.execute(select(User).where(User.email == "founder@neworg.com"))).scalar_one()
    assert str(founder.tenant_id) == tenant_id


def test_middleware_context_from_token():
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    staff_token, _ = create_access_token(str(user_id), tenant_id=tenant_id)
    candidate_token, _ = create_access_token(str(user_id))

    assert tenancy.context_from_token(staff_token) == TenantContext(SCOPE_TENANT, tenant_id=tenant_id, user_id=user_id)
    assert tenancy.context_from_token(candidate_token).scope == "candidate"
    assert tenancy.context_from_token("not-a-jwt").scope == "public"
    assert tenancy.context_from_token(None).scope == "public"
