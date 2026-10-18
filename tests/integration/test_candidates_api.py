"""
تست یکپارچه‌سازی پورتال کارجو، پاسخ به پیشنهاد، آپلود رزومه و جستجوی پیشرفته‌ی HR.
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.core.search_query import resume_has_skill_condition
from app.models import Application, Candidate, Resume, StatusHistory
from tests.integration.conftest import auth_headers

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


async def test_profile_is_created_on_first_visit_and_updated(client, db_session, make_user):
    user = await make_user(role="Candidate", email="sara@example.com")
    headers = auth_headers(user)

    first_visit = await client.get("/api/v1/candidates/me", headers=headers)
    assert first_visit.status_code == 200
    assert first_visit.json()["first_name"] == "sara"  # پروفایل حداقلی از روی ایمیل

    update = await client.put(
        "/api/v1/candidates/me",
        json={"first_name": "Sara", "last_name": "Ahmadi", "location": "Tehran", "skills": ["Python", "SQL"]},
        headers=headers,
    )
    assert update.status_code == 200

    candidate = (await db_session.execute(select(Candidate).where(Candidate.user_id == user.id))).scalar_one()
    assert (candidate.first_name, candidate.location, candidate.skills) == ("Sara", "Tehran", ["Python", "SQL"])


async def test_candidate_accepts_offer(client, db_session, make_application):
    application, candidate_user, _ = await make_application(status="Offer")
    headers = auth_headers(candidate_user)

    inbox = await client.get("/api/v1/candidates/me/offers", headers=headers)
    assert [item["application_id"] for item in inbox.json()["items"]] == [str(application.id)]

    response = await client.put(
        f"/api/v1/candidates/me/applications/{application.id}/respond", json={"decision": "accept"}, headers=headers
    )

    assert response.status_code == 200
    await db_session.refresh(application)
    assert application.current_status == "Accepted"
    history = (
        await db_session.execute(select(StatusHistory).where(StatusHistory.application_id == application.id))
    ).scalar_one()
    assert (history.old_status, history.new_status) == ("Offer", "Accepted")


async def test_candidate_cannot_respond_to_someone_elses_application(client, make_user, make_application):
    application, _, _ = await make_application(status="Offer")
    another_candidate = await make_user(role="Candidate")

    response = await client.put(
        f"/api/v1/candidates/me/applications/{application.id}/respond",
        json={"decision": "accept"},
        headers=auth_headers(another_candidate),
    )

    assert response.status_code == 404


async def test_resume_upload_creates_resume_and_draft_application(client, db_session, make_application, enqueued_tasks):
    _, _, job = await make_application()  # فقط برای داشتن یک آگهی واقعی
    applicant = (await make_application(job=job))[1]

    response = await client.post(
        "/api/v1/resumes/upload",
        data={"job_id": str(job.id)},
        files={"file": ("my-cv.pdf", MINIMAL_PDF, "application/pdf")},
        headers=auth_headers(applicant),
    )

    assert response.status_code == 202
    application_id = uuid.UUID(response.json()["application_id"])
    application = await db_session.get(Application, application_id)
    assert application.current_status == "Draft" and application.job_id == job.id

    resume = (
        await db_session.execute(select(Resume).where(Resume.candidate_id == application.candidate_id))
    ).scalar_one()
    assert resume.file_url.endswith("_my-cv.pdf")
    # پردازش هوش مصنوعی رزومه به صف پس‌زمینه سپرده شده است
    assert enqueued_tasks[0][0] == "process_resume_task"
    assert enqueued_tasks[0][1] == (str(application_id), resume.file_url)


async def test_resume_upload_rejects_unsupported_format(client, db_session, make_application):
    _, candidate_user, job = await make_application()

    response = await client.post(
        "/api/v1/resumes/upload",
        data={"job_id": str(job.id)},
        files={"file": ("cv.txt", b"plain text", "text/plain")},
        headers=auth_headers(candidate_user),
    )

    assert response.status_code == 400
    assert (await db_session.execute(select(Resume))).first() is None


async def test_hr_search_combines_full_text_skills_and_score(client, db_session, make_user, make_application):
    application, _, _ = await make_application(status="Applied", score_ai=85)
    db_session.add(
        Resume(
            candidate_id=application.candidate_id,
            file_url="http://test/media/cv.pdf",
            raw_text="Senior backend engineer: Python, Django and Node.js microservices",
            skill_analysis={"skills": ["Python", "Django", "Node.js"], "total_experience_years": 6.0},
        )
    )
    await db_session.flush()
    headers = auth_headers(await make_user(role="HR_Manager"))

    async def search(**params) -> list[str]:
        response = await client.get("/api/v1/candidates/search/", params=params, headers=headers)
        assert response.status_code == 200
        return [item["candidate_id"] for item in response.json()["items"]]

    expected = [str(application.candidate_id)]
    assert await search(q="python AND django") == expected  # Case-Insensitive + AND
    assert await search(q="Rust OR Node") == expected  # OR + توکنایز درست «Node.js»
    assert await search(q="Python AND Rust") == []
    assert await search(skills=["django"], min_experience_years=5) == expected
    assert await search(min_ai_score=90) == []
    assert (
        await client.get("/api/v1/candidates/search/", params={"min_ai_score": 101}, headers=headers)
    ).status_code == 422


async def test_skill_filter_is_case_insensitive_requires_every_skill_and_tolerates_bad_data(
    client, db_session, make_user, make_application
):
    application, _, _ = await make_application(status="Applied")
    db_session.add_all(
        [
            Resume(
                candidate_id=application.candidate_id,
                file_url="http://test/media/a.pdf",
                skill_analysis={"skills": ["FastAPI", "PostgreSQL"], "total_experience_years": 3.0},
            ),
            # مهارت دوم در رزومه‌ی دیگرِ همان کارجو — هر مهارت کافی است در یکی از رزومه‌هایش باشد
            Resume(
                candidate_id=application.candidate_id,
                file_url="http://test/media/b.pdf",
                skill_analysis={"skills": ["Kubernetes"], "total_experience_years": 1.0},
            ),
            # ساختار نامعتبر (skills غیرآرایه) نه درج را خراب می‌کند نه جستجو را
            Resume(
                candidate_id=application.candidate_id,
                file_url="http://test/media/c.pdf",
                skill_analysis={"skills": "x"},
            ),
        ]
    )
    await db_session.flush()
    headers = auth_headers(await make_user(role="HR_Manager"))

    async def search(**params) -> list[str]:
        response = await client.get("/api/v1/candidates/search/", params=params, headers=headers)
        assert response.status_code == 200
        return [item["candidate_id"] for item in response.json()["items"]]

    expected = [str(application.candidate_id)]
    assert await search(skills=["fastapi", "KUBERNETES"]) == expected
    assert await search(skills=["fastapi", "rust"]) == []
    assert await search(min_experience_years=3) == expected
    assert await search(min_experience_years=4) == []


async def test_skill_filter_condition_uses_the_gin_index(db_session):
    """عبارت شرط مهارت در کوئری دقیقاً با عبارت ایندکس GIN یکی است (پستگرس ایندکس را به کار می‌گیرد)."""
    condition = resume_has_skill_condition(Resume.skill_analysis, "Django").compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    # جدول تست تقریباً خالی است و برنامه‌ریز Seq Scan را ارزان‌تر می‌بیند؛ فقط امکان استفاده از ایندکس سنجیده می‌شود
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (await db_session.execute(text(f"EXPLAIN SELECT id FROM resumes WHERE {condition}"))).scalars().all()
    assert any("ix_resumes_skill_keys_gin" in line for line in plan), plan
