"""
تست یکپارچه‌سازی سرویس مصاحبه: زمان‌بندی، اعتبارسنجی نقش مصاحبه‌کننده و ثبت ارزیابی در جدول interviews.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.models import Interview
from tests.integration.conftest import auth_headers


def _interview_payload(application_id, interviewer_id) -> dict:
    return {
        "application_id": str(application_id),
        "interviewer_id": str(interviewer_id),
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "meeting_link": "https://meet.example.com/abc-defg-hij",
    }


async def test_hr_schedules_interview_and_assigned_interviewer_evaluates_it(
    client, db_session, make_user, make_application
):
    application, _, _ = await make_application(status="Technical Interview")
    hr_manager = await make_user(role="HR_Manager")
    interviewer = await make_user(role="Interviewer")

    created = await client.post(
        "/api/v1/interviews/",
        json=_interview_payload(application.id, interviewer.id),
        headers=auth_headers(hr_manager),
    )
    assert created.status_code == 201
    interview_id = uuid.UUID(created.json()["interview_id"])
    assert created.json()["status"] == "Pending"
    assert created.json()["candidate_name"] == "Sara Ahmadi"

    # مصاحبه‌کننده فقط مصاحبه‌های خودش را می‌بیند
    own_list = await client.get("/api/v1/interviews/", headers=auth_headers(interviewer))
    assert [item["interview_id"] for item in own_list.json()["items"]] == [str(interview_id)]

    evaluation = await client.put(
        f"/api/v1/interviews/{interview_id}/evaluation",
        json={
            "evaluation_scores": {"technical_skill": 9, "communication": 6},
            "feedback_text": "Strong backend skills.",
        },
        headers=auth_headers(interviewer),
    )
    assert evaluation.status_code == 200

    interview = await db_session.get(Interview, interview_id, populate_existing=True)
    assert interview.status == "Completed"
    assert interview.overall_score == 7.5  # میانگین را سرور حساب می‌کند
    assert interview.evaluation_scores == {"technical_skill": 9, "communication": 6}
    assert interview.evaluated_at is not None


async def test_interviewer_must_have_interviewer_or_hr_role(client, make_user, make_application):
    application, candidate_user, _ = await make_application()
    hr_manager = await make_user(role="HR_Manager")

    response = await client.post(
        "/api/v1/interviews/",
        json=_interview_payload(application.id, candidate_user.id),
        headers=auth_headers(hr_manager),
    )

    assert response.status_code == 422


async def test_other_interviewer_cannot_evaluate_and_invalid_criteria_are_rejected(client, make_user, make_application):
    application, _, _ = await make_application()
    hr_manager = await make_user(role="HR_Manager")
    assigned = await make_user(role="Interviewer")
    outsider = await make_user(role="Interviewer")
    interview_id = (
        await client.post(
            "/api/v1/interviews/",
            json=_interview_payload(application.id, assigned.id),
            headers=auth_headers(hr_manager),
        )
    ).json()["interview_id"]
    body = {"evaluation_scores": {"technical_skill": 8}, "feedback_text": "ok"}

    forbidden = await client.put(
        f"/api/v1/interviews/{interview_id}/evaluation", json=body, headers=auth_headers(outsider)
    )
    invalid = await client.put(
        f"/api/v1/interviews/{interview_id}/evaluation",
        json={"evaluation_scores": {"charisma": 8}, "feedback_text": "ok"},
        headers=auth_headers(assigned),
    )

    assert forbidden.status_code == 403
    assert invalid.status_code == 422


async def test_cancelling_interview_deletes_row(client, db_session, make_user, make_application):
    application, _, _ = await make_application()
    hr_manager = await make_user(role="HR_Manager")
    interviewer = await make_user(role="Interviewer")
    interview_id = uuid.UUID(
        (
            await client.post(
                "/api/v1/interviews/",
                json=_interview_payload(application.id, interviewer.id),
                headers=auth_headers(hr_manager),
            )
        ).json()["interview_id"]
    )

    response = await client.delete(f"/api/v1/interviews/{interview_id}", headers=auth_headers(hr_manager))

    assert response.status_code == 204
    assert await db_session.get(Interview, interview_id, populate_existing=True) is None
