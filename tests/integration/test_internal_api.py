"""
تست یکپارچه‌ی مسیرهای داخلی سرویس‌به‌سرویس (app/routers/internal.py) — Zero-Trust:

- بدون X-Internal-Auth، توکن منقضی، audience اشتباه یا امضای کلید ناشناخته ← 401؛ توکن معتبر ← 200.
- درخواستی که از Gateway/Ingress عمومی رد شده (X-Forwarded-For) ← 404 (مسیر از اینترنت وجود ندارد).
- داده با RLS به سازمانِ داخل توکن محدود است: توکن سازمان دیگر ← 404، توکن بی‌سازمان ← 403.
- مسیر واقعی: Worker تولید سؤال، پروفایل کارجو را با توکن امضاشده از بک‌اند می‌گیرد (نه از دیتابیس).
"""

import time

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.service_auth import SERVICE_AUTH_HEADER, issue_service_token
from app.genai import service as genai_service
from app.main import app
from app.models import InterviewQuestionSet, Job
from tests.integration.test_genai_api import _processed_application, fake_generation, same_session_factory  # noqa: F401
from tests.unit.test_service_auth import _signed, keys  # noqa: F401

WHOAMI = "/api/v1/internal/whoami"


def _profile_url(application_id) -> str:
    return f"/api/v1/internal/applications/{application_id}/interview-profile"


async def test_internal_endpoint_requires_valid_service_token(client, keys):  # noqa: F811
    now = int(time.time())
    rejected = {
        "missing header": {},
        "expired": {SERVICE_AUTH_HEADER: _signed(keys["worker"], iat=now - 600, nbf=now - 600, exp=now - 300)},
        "wrong audience": {SERVICE_AUTH_HEADER: _signed(keys["worker"], aud="grafana")},
        "unknown signing key": {SERVICE_AUTH_HEADER: _signed(keys["rogue"])},
        "user access token": {SERVICE_AUTH_HEADER: "Bearer eyJhbGciOiJIUzI1NiJ9.e30.x"},
    }
    for case, headers in rejected.items():
        response = await client.get(WHOAMI, headers=headers)
        assert response.status_code == 401, case
        assert response.headers["www-authenticate"] == "ServiceToken"

    ok = await client.get(WHOAMI, headers={SERVICE_AUTH_HEADER: issue_service_token(audience="backend-api")})
    assert ok.status_code == 200
    assert ok.json()["service"] == "worker" and ok.json()["audience"] == "backend-api"


async def test_internal_routes_do_not_exist_through_the_public_edge(client, keys):  # noqa: F811
    token = issue_service_token(audience="backend-api")
    for edge_header in ({"X-Forwarded-For": "203.0.113.7"}, {"X-Real-IP": "203.0.113.7"}):
        response = await client.get(WHOAMI, headers={SERVICE_AUTH_HEADER: token, **edge_header})
        assert response.status_code == 404


async def test_profile_is_limited_to_the_tenant_in_the_token(
    client, db_session, make_application, make_tenant, keys  # noqa: F811
):
    application, _ = await _processed_application(db_session, make_application)
    other_org, _ = await make_tenant("Other Org")

    def headers(tenant_id):
        return {SERVICE_AUTH_HEADER: issue_service_token(audience="backend-api", tenant_id=tenant_id)}

    own = await client.get(_profile_url(application.id), headers=headers(application.tenant_id))
    assert own.status_code == 200
    profile = own.json()["profile"]
    assert {"job_posting", "candidate_profile", "fit_analysis"} <= set(profile)
    assert "sara@example.com" not in str(profile)  # بدون اطلاعات شخصی

    assert (await client.get(_profile_url(application.id), headers=headers(other_org.id))).status_code == 404
    assert (await client.get(_profile_url(application.id), headers=headers(None))).status_code == 403


async def test_worker_fetches_profile_over_signed_internal_call(
    client,  # Override دیتابیس تست برای همان برنامه‌ای که Worker صدا می‌زند
    db_session,
    make_application,
    same_session_factory,  # noqa: F811
    keys,  # noqa: F811
    monkeypatch,
):
    """کار Worker: مسیر HTTP داخلی با توکن سرویس محدود به سازمان؛ همان پروفایل مسیر دیتابیس را می‌گیرد."""
    application, _ = await _processed_application(db_session, make_application)
    expected = await genai_service.build_profile_for_application(db_session, application)
    question_set = InterviewQuestionSet(
        application_id=application.id,
        job_id=application.job_id,
        candidate_id=application.candidate_id,
        requested_by=(await db_session.get(Job, application.job_id)).created_by,
        tenant_id=application.tenant_id,
        status="pending",
        language="fa",
        question_count=3,
        difficulty="mixed",
        focus_skills=[],
        prompt_version="test",
    )
    db_session.add(question_set)
    await db_session.commit()

    sent_headers = []

    class InternalClient(AsyncClient):
        def __init__(self, **kwargs):
            kwargs.pop("timeout", None)
            super().__init__(transport=ASGITransport(app=app), base_url="http://backend-api:8000")

        async def get(self, url, headers=None, **kwargs):
            sent_headers.append(headers or {})
            return await super().get(url, headers=headers, **kwargs)

    monkeypatch.setattr(settings, "INTERNAL_API_URL", "http://backend-api:8000")
    monkeypatch.setattr(genai_service.httpx, "AsyncClient", InternalClient)
    calls = fake_generation(monkeypatch)

    await genai_service.run_question_set_job(question_set.id, same_session_factory)

    assert sent_headers and SERVICE_AUTH_HEADER in sent_headers[0]
    assert calls[0][0] == expected  # همان پروفایل، این بار از سرویس بک‌اند
    stored = (
        await db_session.execute(select(InterviewQuestionSet).where(InterviewQuestionSet.id == question_set.id))
    ).scalar_one()
    assert stored.status == "completed"
