"""
تست یکپارچه‌سازی بورد کانبان: ماشین وضعیت صلب + جدول status_history + داشبورد تحلیلی.
"""

from sqlalchemy import select

from app.models import Application, StatusHistory
from tests.integration.conftest import auth_headers


def _move(current: str, new: str) -> dict:
    return {"current_status": current, "new_status": new}


async def _history(db_session, application_id) -> list[tuple[str, str]]:
    rows = await db_session.execute(
        select(StatusHistory.old_status, StatusHistory.new_status)
        .where(StatusHistory.application_id == application_id)
        .order_by(StatusHistory.changed_at)
    )
    return [tuple(row) for row in rows.all()]


async def test_allowed_transition_updates_status_and_writes_history(client, db_session, make_user, make_application):
    application, _, _ = await make_application(status="Draft")
    hr_manager = await make_user(role="HR_Manager")

    response = await client.put(
        f"/api/v1/applications/{application.id}/status",
        json=_move("Draft", "Applied"),
        headers=auth_headers(hr_manager),
    )

    assert response.status_code == 200
    assert response.json()["previous_status"] == "Draft"
    await db_session.refresh(application)
    assert application.current_status == "Applied"
    history = (
        await db_session.execute(select(StatusHistory).where(StatusHistory.application_id == application.id))
    ).scalar_one()
    assert (history.old_status, history.new_status, history.changed_by) == ("Draft", "Applied", hr_manager.id)


async def test_skipping_stages_is_rejected_and_database_is_unchanged(client, db_session, make_user, make_application):
    application, _, _ = await make_application(status="Screening")
    application_id = application.id
    hr_manager = await make_user(role="HR_Manager")

    response = await client.put(
        f"/api/v1/applications/{application_id}/status",
        json=_move("Screening", "Hired"),
        headers=auth_headers(hr_manager),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Business Logic Violation"
    assert (await db_session.get(Application, application_id, populate_existing=True)).current_status == "Screening"
    assert await _history(db_session, application_id) == []


async def test_stale_current_status_from_client_is_rejected(client, db_session, make_user, make_application):
    application, _, _ = await make_application(status="Applied")
    hr_manager = await make_user(role="HR_Manager")

    response = await client.put(
        f"/api/v1/applications/{application.id}/status",
        json=_move("Draft", "Applied"),  # کلاینت وضعیت قدیمی را دیده
        headers=auth_headers(hr_manager),
    )

    assert response.status_code == 400


async def test_candidate_cannot_move_cards(client, make_application):
    application, candidate_user, _ = await make_application(status="Draft")

    response = await client.put(
        f"/api/v1/applications/{application.id}/status",
        json=_move("Draft", "Applied"),
        headers=auth_headers(candidate_user),
    )

    assert response.status_code == 403


async def test_kanban_list_returns_cards_of_one_job(client, make_user, make_application):
    first, _, job = await make_application(status="Applied", score_ai=82)
    await make_application(status="Draft")  # درخواستی برای یک آگهی دیگر
    hr_manager = await make_user(role="HR_Manager")

    response = await client.get(
        "/api/v1/applications/", params={"job_id": str(job.id)}, headers=auth_headers(hr_manager)
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["application_id"] == str(first.id)
    assert items[0]["candidate_name"] == "Sara Ahmadi"
    assert items[0]["score_ai"] == 82


async def test_full_pipeline_feeds_the_recruitment_funnel(client, db_session, make_user, make_application):
    """کارجو کل مسیر را تا Hired طی می‌کند؛ قیف تحلیلی باید در هر مرحله دقیقاً ۱ نشان دهد."""
    application, _, job = await make_application(status="Draft")
    application_id, job_id = application.id, job.id  # قبل از rollback احتمالی API (که اشیاء را منقضی می‌کند)
    hr_manager = await make_user(role="HR_Manager")
    headers = auth_headers(hr_manager)
    path = ["Draft", "Applied", "Screening", "Technical Interview", "HR Interview", "Offer", "Accepted", "Hired"]

    for current, new in zip(path, path[1:]):
        response = await client.put(
            f"/api/v1/applications/{application_id}/status", json=_move(current, new), headers=headers
        )
        assert response.status_code == 200, (current, new)

    # وضعیت نهایی است — هیچ حرکت دیگری مجاز نیست
    terminal = await client.put(
        f"/api/v1/applications/{application_id}/status", json=_move("Hired", "Rejected"), headers=headers
    )
    assert terminal.status_code == 400

    assert len(await _history(db_session, application_id)) == 7
    funnel = await client.get("/api/v1/analytics/funnel", params={"job_id": str(job_id)}, headers=headers)
    assert funnel.status_code == 200
    assert {stage["stage"]: stage["count"] for stage in funnel.json()["stages"]} == {stage: 1 for stage in path[1:]}

    trend = await client.get("/api/v1/analytics/applications-trend", params={"days": 7}, headers=headers)
    assert sum(day["count"] for day in trend.json()["series"]) == 1
    assert (await db_session.get(Application, application_id)).current_status == "Hired"
