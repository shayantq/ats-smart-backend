"""
تست یکپارچه‌سازی سرویس آگهی‌ها: درخواست HTTP واقعی به /api/v1/jobs و بررسی مستقیم جدول jobs.
"""

import uuid

from sqlalchemy import func, select

from app.models import Job
from tests.integration.conftest import auth_headers

JOB_PAYLOAD = {
    "title": "Backend Python Developer",
    "department": "Engineering",
    "description": "Building APIs with FastAPI and PostgreSQL",
    "skills_required": ["Python", "FastAPI", "Docker"],
    "salary_range": "40M-60M",
    "required_seniority": "Senior",
    "location": "Tehran",
}


async def _job_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(Job))).scalar_one()


async def test_hr_creates_job_and_it_is_persisted_in_jobs_table(client, db_session, make_user):
    hr_manager = await make_user(role="HR_Manager")

    response = await client.post("/api/v1/jobs/", json=JOB_PAYLOAD, headers=auth_headers(hr_manager))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "Active"

    # ثبت واقعی در جدول — نه فقط پاسخ API
    job = (await db_session.execute(select(Job).where(Job.id == uuid.UUID(body["job_id"])))).scalar_one()
    assert job.title == JOB_PAYLOAD["title"]
    assert job.skills_required == JOB_PAYLOAD["skills_required"]
    assert job.required_seniority == "Senior"
    assert job.status == "Active"
    assert job.created_by == hr_manager.id
    assert job.created_at is not None


async def test_candidate_cannot_create_job_and_nothing_is_written(client, db_session, make_user):
    candidate = await make_user(role="Candidate")

    response = await client.post("/api/v1/jobs/", json=JOB_PAYLOAD, headers=auth_headers(candidate))

    assert response.status_code == 403
    assert await _job_count(db_session) == 0


async def test_create_job_without_token_returns_401(client, db_session):
    response = await client.post("/api/v1/jobs/", json=JOB_PAYLOAD)

    assert response.status_code == 401
    assert await _job_count(db_session) == 0


async def test_create_job_with_invalid_payload_returns_422(client, db_session, make_user):
    hr_manager = await make_user(role="HR_Manager")

    response = await client.post("/api/v1/jobs/", json={"department": "No title"}, headers=auth_headers(hr_manager))

    assert response.status_code == 422
    assert await _job_count(db_session) == 0


async def test_public_job_list_with_status_filter(client, make_user):
    admin = await make_user(role="Admin")
    headers = auth_headers(admin)
    first = (await client.post("/api/v1/jobs/", json=JOB_PAYLOAD, headers=headers)).json()
    second = (await client.post("/api/v1/jobs/", json={**JOB_PAYLOAD, "title": "Frontend"}, headers=headers)).json()
    await client.delete(f"/api/v1/jobs/{second['job_id']}", headers=headers)

    all_jobs = await client.get("/api/v1/jobs/")  # مسیر عمومی — بدون توکن
    active_jobs = await client.get("/api/v1/jobs/", params={"status": "Active"})

    assert all_jobs.status_code == 200
    assert {item["job_id"] for item in all_jobs.json()["items"]} == {first["job_id"], second["job_id"]}
    assert [item["job_id"] for item in active_jobs.json()["items"]] == [first["job_id"]]


async def test_close_job_is_a_soft_delete(client, db_session, make_user):
    hr_manager = await make_user(role="HR_Manager")
    headers = auth_headers(hr_manager)
    job_id = (await client.post("/api/v1/jobs/", json=JOB_PAYLOAD, headers=headers)).json()["job_id"]

    response = await client.delete(f"/api/v1/jobs/{job_id}", headers=headers)

    assert response.status_code == 200
    # رکورد پاک نشده؛ فقط وضعیتش Closed شده
    job = (await db_session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one()
    assert job.status == "Closed"


async def test_close_unknown_job_returns_404(client, make_user):
    hr_manager = await make_user(role="HR_Manager")

    response = await client.delete(f"/api/v1/jobs/{uuid.uuid4()}", headers=auth_headers(hr_manager))

    assert response.status_code == 404
