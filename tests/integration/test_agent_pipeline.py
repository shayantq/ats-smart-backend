"""
تست یکپارچه‌ی اکوسیستم چندعاملی پردازش رزومه — مسیر واقعی:

    POST /api/v1/resumes/upload (فایل خام DOCX) ← کار process_resume_task در صف «resumes» (RQ روی Redis حافظه‌ای)
    ← عامل ناظر: استخراج متن و پارس یک‌بار، سه عامل تخصصی موازی، جمع‌بندی و نمره
    ← resumes.agent_analysis (رمزشده)، skill_analysis (همان شکل قبلی)، applications.score_ai

و بازگشت فوری: با RESUME_PIPELINE=linear همان خط لوله‌ی ترتیبی قبلی اجرا می‌شود.
"""

import asyncio
import io
import uuid

import fakeredis
import pytest
from docx import Document
from rq import Queue
from sqlalchemy import select, text

from app.agents.schema import SCHEMA_VERSION, UnifiedAnalysis
from app.core import queue as queue_module
from app.core.config import settings
from app.core.crypto import FERNET_PREFIX
from app.core.queue import QUEUE_RESUMES, enqueue_task
from app.models import Application, Job, Resume
from app.routers import resumes as resumes_router
from app.tasks import resume_processing
from tests.integration.conftest import auth_headers

RESUME_LINES = [
    "Sara Ahmadi",
    "sara.ahmadi@mail.test | 09121234567",
    "Summary",
    "Backend developer with 15 years of experience. We collaborated with stakeholders and delivered on time.",
    "Skills",
    "Python (12 years), FastAPI, Docker, Kubernetes, PostgreSQL",
    "Experience",
    "Backend Developer",
    "Acme",
    "2019 - 2023",
    "Education",
    "B.Sc Computer Engineering",
    "University of Tehran",
]


def _docx(lines) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class _SharedSessionFactory:
    """session_factory کار Worker ← همان Session تراکنشی تست (در پایان بسته نمی‌شود)."""

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def rq_redis(monkeypatch, fake_redis_server):
    connection = fakeredis.FakeRedis(server=fake_redis_server)
    monkeypatch.setattr(queue_module, "_get_sync_redis_client", lambda: connection)
    monkeypatch.setattr(queue_module, "_task_queues", {})
    monkeypatch.setattr(resumes_router, "enqueue_task", enqueue_task)
    return connection


async def _upload(client, db_session, make_application, make_user):
    hr = await make_user(role="HR_Manager")
    job = Job(
        title="Backend Developer",
        skills_required=["Python", "Docker"],
        required_seniority="senior",
        location="Tehran",
        description="FastAPI microservices",
        created_by=hr.id,
        tenant_id=hr.tenant_id,
    )
    db_session.add(job)
    await db_session.commit()
    candidate_user = await make_user(role="Candidate")  # پروفایل و درخواست را خود آپلود می‌سازد
    response = await client.post(
        "/api/v1/resumes/upload",
        data={"job_id": str(job.id)},
        files={
            "file": (
                "resume.docx",
                _docx(RESUME_LINES),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=auth_headers(candidate_user),
    )
    assert response.status_code == 202, response.text
    resume = (
        (await db_session.execute(select(Resume).where(Resume.tenant_id == job.tenant_id).order_by(Resume.id)))
        .scalars()
        .first()
    )
    application = (
        await db_session.execute(select(Application).where(Application.candidate_id == resume.candidate_id))
    ).scalar_one()
    return hr, job, resume, application


async def test_upload_runs_the_multi_agent_pipeline_through_the_rq_queue(
    client, db_session, make_application, make_user, rq_redis
):
    hr, _, resume, application = await _upload(client, db_session, make_application, make_user)
    resume_id, application_id, file_url = resume.id, application.id, resume.file_url
    hr_headers = auth_headers(hr)
    await asyncio.sleep(0.3)  # مسیر آپلود کار را با create_task در پس‌زمینه به صف می‌دهد

    # کار در صف «resumes» با همان ورودی قبلی (شناسه‌ی درخواست + آدرس فایل)، نه متن یا داده‌ی رزومه
    jobs = Queue(QUEUE_RESUMES, connection=rq_redis).get_jobs()
    assert [job.func_name for job in jobs] == ["app.tasks.resume_processing.process_resume_task"]
    assert jobs[0].args == (str(application_id), file_url)

    # همان کاری که Worker با این ورودی انجام می‌دهد (روی Session تراکنشی تست)
    await resume_processing._process_resume_async(*jobs[0].args, _SharedSessionFactory(db_session))

    raw = (
        (
            await db_session.execute(
                text("SELECT agent_analysis, raw_text, parsed_data FROM resumes WHERE id = :id"), {"id": resume_id}
            )
        )
        .mappings()
        .one()
    )
    for column in ("agent_analysis", "raw_text", "parsed_data"):
        assert raw[column].startswith(FERNET_PREFIX), column  # رمزشده در دیتابیس
    assert "Acme" not in raw["agent_analysis"] and "Python" not in raw["agent_analysis"]

    db_session.expire_all()
    stored = await db_session.get(Resume, resume_id)
    analysis = UnifiedAnalysis.model_validate(stored.agent_analysis)
    assert analysis.schema_version == SCHEMA_VERSION and analysis.status == "completed"
    assert {"Python", "FastAPI", "Docker", "Kubernetes"} <= {item.name for item in analysis.skills.items}
    assert analysis.experience.total_experience_years == 4.0
    assert {flag.code for flag in analysis.flags} >= {"claimed_years_exceed_history", "skill_years_exceed_career"}
    assert {c.code for c in analysis.conflicts_resolved} >= {"skill_years_capped", "claimed_total_overridden"}
    assert analysis.soft_skills.items and analysis.matching.score is not None

    # موازی: هر سه عامل بعد از توزیع ناظر شروع و پیش از جمع‌بندی تمام شده‌اند و پنجره‌هایشان هم‌پوشانی دارد
    timings = analysis.timings_ms
    windows = [timings[name] for name in ("skill_extraction", "experience_validation", "culture_fit_soft_skills")]
    assert all(w.start_ms >= timings["supervisor_dispatch"].end_ms for w in windows)
    assert all(w.end_ms <= timings["supervisor_aggregate"].start_ms for w in windows)
    assert max(w.start_ms for w in windows) < min(w.end_ms for w in windows)

    # سازگاری با بقیه‌ی سیستم: skill_analysis همان شکل، score_ai همان نمره‌ی ناظر
    assert set(stored.skill_analysis) == {"skills", "total_experience_years", "experience_entries"}
    assert (await db_session.get(Application, application_id)).score_ai == round(analysis.matching.score)

    # HR همان JSON یکپارچه را در جزئیات رزومه می‌بیند
    detail = await client.get(f"/api/v1/resumes/{resume_id}", headers=hr_headers)
    assert detail.status_code == 200 and detail.json()["agent_analysis"]["schema_version"] == SCHEMA_VERSION


async def test_linear_pipeline_still_works_as_instant_rollback(
    client, db_session, make_application, make_user, monkeypatch
):
    _, _, resume, application = await _upload(client, db_session, make_application, make_user)
    resume_id, application_id, file_url = resume.id, application.id, resume.file_url
    monkeypatch.setattr(settings, "RESUME_PIPELINE", "linear")

    await resume_processing._process_resume_async(str(application_id), file_url, _SharedSessionFactory(db_session))

    db_session.expire_all()
    stored = await db_session.get(Resume, resume_id)
    assert stored.agent_analysis is None  # خط لوله‌ی قبلی JSON یکپارچه نمی‌سازد
    assert "Python" in stored.skill_analysis["skills"] and stored.raw_text
    assert (await db_session.get(Application, application_id)).score_ai is not None


async def test_unreadable_file_is_logged_without_saving_or_crashing(
    client, db_session, make_application, make_user, monkeypatch, caplog
):
    _, _, resume, application = await _upload(client, db_session, make_application, make_user)
    resume_id, file_url = resume.id, resume.file_url
    monkeypatch.setattr(resume_processing, "_download_file", lambda file_url: b"not a real docx")

    await resume_processing._process_resume_async(str(application.id), file_url, _SharedSessionFactory(db_session))

    db_session.expire_all()
    stored = await db_session.get(Resume, resume_id)
    assert stored.agent_analysis is None and stored.raw_text is None
    assert all(file_url not in record.getMessage() for record in caplog.records)  # بدون آدرس فایل در لاگ


async def test_missing_resume_record_is_logged(db_session, caplog):
    await resume_processing._process_resume_async(
        str(uuid.uuid4()), "http://test/media/resumes/missing.docx", _SharedSessionFactory(db_session)
    )
    assert any("رکورد رزومه متناظر" in record.getMessage() for record in caplog.records)
