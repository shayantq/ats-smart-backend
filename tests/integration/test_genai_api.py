"""
تست یکپارچه‌سازی API تولید سؤال مصاحبه (app/routers/genai.py) و کار پس‌زمینه‌ی آن (app/genai/service.py)
روی دیتابیس واقعی — مدل زبانی با یک کلاینت شبیه‌سازی‌شده جایگزین می‌شود (CI به سرویس بیرونی وصل نمی‌شود).
"""

import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.genai import service as genai_service
from app.genai.client import CompletionResult, GenAIProviderError
from app.models import Interview, InterviewQuestion, InterviewQuestionSet, Resume
from app.routers import genai as genai_router
from tests.integration.conftest import auth_headers
from tests.unit.test_genai_contract import VALID_QUESTION

BASE = "/api/v1/genai"


@pytest.fixture
def genai_enabled(monkeypatch, enqueued_tasks):
    monkeypatch.setattr(settings, "GENAI_BASE_URL", "http://llm.test/v1")
    monkeypatch.setattr(settings, "GENAI_MODEL", "test-model")

    async def fake_enqueue(func, *args, **kwargs):
        enqueued_tasks.append((func.__name__, args))
        return "test-job-id"

    monkeypatch.setattr(genai_router, "enqueue_task", fake_enqueue)


@pytest.fixture
def same_session_factory(db_session):
    """کار Worker همان تراکنش تست را ببیند (SAVEPOINT) — به‌جای اتصال جدای worker_session_factory."""

    @asynccontextmanager
    async def factory():
        yield db_session

    return factory


def fake_generation(monkeypatch, questions=None, error=None):
    calls = []

    def generate(profile, options):
        calls.append((profile, options))
        if error:
            raise error
        payload = {"focus_summary": "تمرکز بر PostgreSQL و شکاف Kafka", "questions": questions or [VALID_QUESTION] * 3}
        return genai_service.GenerationResult(
            question_set=genai_service.parse_question_set(json.dumps(payload, ensure_ascii=False)),
            completion=CompletionResult(json.dumps(payload), "test-model", 900, 400, 1234, "stop"),
            repaired=False,
        )

    monkeypatch.setattr(genai_service, "_generate_with_settings", generate)
    return calls


async def _processed_application(db_session, make_application):
    application, candidate_user, job = await make_application(status="Screening", score_ai=70)
    job.skills_required = ["Python", "PostgreSQL", "Kafka"]
    job.required_seniority = "Mid-Level"
    db_session.add(
        Resume(
            candidate_id=application.candidate_id,
            file_url="http://test/media/cv.pdf",
            raw_text="Sara Ahmadi sara@example.com Python developer",
            parsed_data={"personal_info": {"name": "Sara Ahmadi", "email": "sara@example.com"}},
            skill_analysis={"skills": ["Python", "PostgreSQL"], "total_experience_years": 3.0},
        )
    )
    await db_session.commit()
    return application, candidate_user


async def test_full_flow_request_generate_review_and_question_bank(
    client, db_session, make_user, make_application, genai_enabled, enqueued_tasks, same_session_factory, monkeypatch
):
    application, _ = await _processed_application(db_session, make_application)
    hr_headers = auth_headers(await make_user(role="HR_Manager"))

    response = await client.post(
        f"{BASE}/interview-questions",
        json={"application_id": str(application.id), "question_count": 3, "focus_skills": ["Kafka"], "language": "fa"},
        headers=hr_headers,
    )
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "pending" and accepted["status_url"].endswith(accepted["id"])
    assert enqueued_tasks == [("generate_interview_questions_task", (accepted["id"],))]

    pending = (await client.get(accepted["status_url"], headers=hr_headers)).json()
    assert pending["status"] == "pending" and pending["questions"] == []

    # کار Worker
    calls = fake_generation(monkeypatch)
    question_set = await db_session.get(InterviewQuestionSet, application_id_set := accepted["id"])
    await genai_service.run_question_set_job(question_set.id, same_session_factory)
    profile, options = calls[0]
    assert options == {"question_count": 3, "difficulty": "mixed", "focus_skills": ["Kafka"], "language": "fa"}
    assert "Sara Ahmadi" not in json.dumps(profile, ensure_ascii=False)
    assert profile["fit_analysis"]["missing_required_skills"] == ["Kafka"]

    done = (await client.get(f"{BASE}/interview-questions/{application_id_set}", headers=hr_headers)).json()
    assert done["status"] == "completed" and len(done["questions"]) == 3
    assert done["usage"] == {"prompt_tokens": 900, "completion_tokens": 400, "latency_ms": 1234}
    assert [question["position"] for question in done["questions"]] == [1, 2, 3]
    stored = await db_session.get(InterviewQuestionSet, question_set.id)
    assert stored.input_profile["fit_analysis"]["gaps"] and stored.provider_model == "test-model"

    # بازبینی مصاحبه‌کننده و بانک سؤال مشترک
    first = done["questions"][0]
    patched = await client.patch(
        f"{BASE}/interview-questions/{application_id_set}/questions/{first['id']}",
        json={"is_approved": True, "interviewer_notes": "<b>عالی</b> برای سطح Mid"},
        headers=hr_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["is_approved"] is True and patched.json()["interviewer_notes"] == "عالی برای سطح Mid"

    bank = (await client.get(f"{BASE}/question-bank", params={"skill": "postgresql"}, headers=hr_headers)).json()
    assert [item["id"] for item in bank["items"]] == [first["id"]]

    listing = (
        await client.get(
            f"{BASE}/interview-questions", params={"application_id": str(application.id)}, headers=hr_headers
        )
    ).json()
    assert [item["id"] for item in listing["items"]] == [application_id_set]


async def test_access_control(
    client, db_session, make_user, make_application, genai_enabled, same_session_factory, monkeypatch
):
    application, candidate_user = await _processed_application(db_session, make_application)
    hr = await make_user(role="HR_Manager")
    created = await client.post(
        f"{BASE}/interview-questions", json={"application_id": str(application.id)}, headers=auth_headers(hr)
    )
    set_url = f"{BASE}/interview-questions/{created.json()['id']}"

    # کارجو هرگز کلید پاسخ‌ها را نمی‌بیند و نمی‌تواند درخواست بدهد
    candidate_headers = auth_headers(candidate_user)
    assert (await client.get(set_url, headers=candidate_headers)).status_code == 403
    assert (
        await client.post(
            f"{BASE}/interview-questions", json={"application_id": str(application.id)}, headers=candidate_headers
        )
    ).status_code == 403

    # مصاحبه‌کننده فقط وقتی مصاحبه‌ی این درخواست به او سپرده شده باشد
    interviewer = await make_user(role="Interviewer")
    assert (await client.get(set_url, headers=auth_headers(interviewer))).status_code == 403
    assert (
        await client.post(
            f"{BASE}/interview-questions",
            json={"application_id": str(application.id)},
            headers=auth_headers(interviewer),
        )
    ).status_code == 403
    db_session.add(Interview(application_id=application.id, interviewer_id=interviewer.id))
    await db_session.commit()
    assert (await client.get(set_url, headers=auth_headers(interviewer))).status_code == 200


async def test_validation_and_preconditions(
    client, db_session, make_user, make_application, genai_enabled, monkeypatch
):
    hr_headers = auth_headers(await make_user(role="HR_Manager"))
    unprocessed, _, _ = await make_application(status="Applied")

    response = await client.post(
        f"{BASE}/interview-questions", json={"application_id": str(unprocessed.id)}, headers=hr_headers
    )
    assert response.status_code == 409  # رزومه هنوز تحلیل نشده

    for invalid in ({"question_count": 2}, {"question_count": 16}, {"language": "de"}, {"unknown": True}):
        body = {"application_id": str(unprocessed.id), **invalid}
        assert (await client.post(f"{BASE}/interview-questions", json=body, headers=hr_headers)).status_code == 422

    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.post(f"{BASE}/interview-questions", json={"application_id": missing}, headers=hr_headers)
    ).status_code == 404

    monkeypatch.setattr(settings, "GENAI_MODEL", "")
    disabled = await client.post(
        f"{BASE}/interview-questions", json={"application_id": str(unprocessed.id)}, headers=hr_headers
    )
    assert disabled.status_code == 503


async def test_retryable_provider_errors_keep_the_set_pending_until_attempts_run_out(
    client, db_session, make_user, make_application, genai_enabled, same_session_factory, monkeypatch
):
    application, _ = await _processed_application(db_session, make_application)
    created = await client.post(
        f"{BASE}/interview-questions",
        json={"application_id": str(application.id)},
        headers=auth_headers(await make_user(role="HR_Manager")),
    )
    set_id = (await db_session.execute(select(InterviewQuestionSet.id))).scalar_one()
    assert str(set_id) == created.json()["id"]
    fake_generation(monkeypatch, error=GenAIProviderError("rate limited", retryable=True, status_code=429))

    for attempt in range(1, genai_service.MAX_ATTEMPTS):
        with pytest.raises(GenAIProviderError):  # صف RQ با فاصله دوباره اجرا می‌کند
            await genai_service.run_question_set_job(set_id, same_session_factory)
        assert (await db_session.get(InterviewQuestionSet, set_id)).status == "pending"

    await genai_service.run_question_set_job(set_id, same_session_factory)  # آخرین تلاش: بدون پرتاب، failed
    final = await db_session.get(InterviewQuestionSet, set_id)
    assert final.status == "failed" and "rate limited" in final.error and final.attempts == genai_service.MAX_ATTEMPTS
    assert (await db_session.execute(select(InterviewQuestion))).first() is None
