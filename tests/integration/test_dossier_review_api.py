"""گردش واقعی بازبینی و حریم خصوصی با دو سازمان ساختگی و دیتابیس موقت."""

import pytest

from app.core.structured_resume import build_structured
from app.core.analysis_evidence import build_analysis
from app.core.tenancy import SYSTEM_CONTEXT
from tests.integration.conftest import auth_headers
from tests.integration import test_tenant_isolation as tenant_fixtures

two_orgs = tenant_fixtures.two_orgs
_raw_rows = tenant_fixtures._raw_rows


@pytest.fixture
async def dossier(db_session, two_orgs):
    a = two_orgs["A"]
    raw = "MIRA HART\nEXPERIENCE\nEngineer | Maple Labs\n2020 - 2024\nSKILLS\nPython"
    parsed = {"structured": build_structured(raw), "_extraction": {"file_sha256": "a" * 64, "status": "completed"}}
    parsed["_evidence_analysis"] = build_analysis(raw, parsed["structured"], {"skills_required": ["Python"]})
    a["application"].resume_id = a["resume"].id
    a["resume"].parsed_data = parsed
    a["resume"].processing_state = {"status": "succeeded", "stage": "complete"}
    await db_session.commit()
    return a


async def test_private_notes_revision_conflict_and_source_edit(client, db_session, dossier, two_orgs, make_user):
    a = dossier
    second = await make_user(role="HR_Manager", tenant=a["company"])
    path = f"/api/v1/dossiers/{a['application'].id}"
    headers = auth_headers(a["hr"])
    state = (await client.get(path + "/review", headers=headers)).json()
    target = next(t for t in state["targets"] if t["target"] == "identity.name")
    body = dict(
        action="correction",
        expected_revision=0,
        reason="Verified visual source",
        target=target["target"],
        source_hash=state["source_hash"],
        anchor=target["anchor"],
        value="Mira Hart",
        evidence_text="Visual source fixture",
    )
    response = await client.post(path + "/events", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["effective_parsed"]["structured"]["identity"]["name"]["value"] == "Mira Hart"
    assert (await client.post(path + "/events", json=body, headers=headers)).status_code == 409
    note = dict(
        action="note",
        expected_revision=1,
        visibility="private",
        reason="Private fixture",
        value="Private synthetic note",
    )
    own = (await client.post(path + "/events", json=note, headers=headers)).json()
    assert own["notes"][0]["payload"]["value"] == "Private synthetic note"
    other = (await client.get(path + "/review", headers=auth_headers(second))).json()
    assert other["notes"] == [] and len(other["events"]) == 1
    assert (await client.get(path + "/review", headers=auth_headers(two_orgs["B"]["hr"]))).status_code == 404
    assert (await client.get(path + "/review", headers=auth_headers(a["candidate_user"]))).status_code == 403
    await db_session.refresh(a["resume"])
    assert a["resume"].parsed_data["structured"]["identity"]["name"]["value"] == "MIRA HART"


async def test_review_payload_encrypted_and_private_note_protected_in_database(client, db_session, dossier, make_user):
    from app.core.tenancy import TenantContext, SCOPE_TENANT

    a = dossier
    second = await make_user(role="HR_Manager", tenant=a["company"])
    appid = a["application"].id
    tenant = a["company"].id
    second_id = second.id
    await client.post(
        f"/api/v1/dossiers/{appid}/events",
        headers=auth_headers(a["hr"]),
        json=dict(
            action="note",
            expected_revision=0,
            visibility="private",
            reason="Private fixture",
            value="Secret fixture text",
        ),
    )
    owner = await _raw_rows(
        db_session, SYSTEM_CONTEXT, "SELECT payload FROM dossier_review_events WHERE application_id=:id", id=appid
    )
    assert len(owner) == 1 and "Secret fixture text" not in owner[0][0]
    hidden = await _raw_rows(
        db_session,
        TenantContext(SCOPE_TENANT, tenant_id=tenant, user_id=second_id),
        "SELECT id FROM dossier_review_events WHERE application_id=:id",
        id=appid,
    )
    assert hidden == []


async def test_comparison_and_batch_do_not_repeat_queued_work_even_after_lease(
    client, db_session, dossier, monkeypatch
):
    from unittest.mock import AsyncMock
    from app.routers import dossier_review

    a = dossier
    appid = a["application"].id
    headers = auth_headers(a["hr"])
    compared = await client.post("/api/v1/dossiers/compare", headers=headers, json={"application_ids": [str(appid)]})
    assert compared.status_code == 200 and compared.json()["ranked"] is False
    enqueue = AsyncMock(return_value="synthetic-job")
    monkeypatch.setattr(dossier_review, "enqueue_task", enqueue)
    first = await client.post("/api/v1/dossiers/batches", headers=headers, json={"application_ids": [str(appid)]})
    assert first.status_code == 202, first.text
    await db_session.refresh(a["resume"])
    a["resume"].processing_state = dict(a["resume"].processing_state, expires_at=0)
    await db_session.commit()
    second = await client.post("/api/v1/dossiers/batches", headers=headers, json={"application_ids": [str(appid)]})
    assert second.status_code == 202
    assert second.json()["items"][str(appid)]["reason"] == "already_active"
    assert enqueue.await_count == 1 and first.json()["message_sent"] is False


async def test_batch_and_comparison_reject_other_job_or_tenant(client, db_session, dossier, two_orgs, make_application):
    from app.models import Job, Resume

    a = dossier
    other, _, _ = await make_application(job=a["job"])
    headers = auth_headers(a["hr"])
    for endpoint in ("compare", "batches"):
        foreign = await client.post(
            f"/api/v1/dossiers/{endpoint}",
            headers=headers,
            json={"application_ids": [str(a["application"].id), str(two_orgs["B"]["application"].id)]},
        )
        assert foreign.status_code == 404
    # درخواست هم‌آگهی بدون رزومهٔ متصل نیز مجاز نیست.
    response = await client.post("/api/v1/dossiers/batches", headers=headers, json={"application_ids": [str(other.id)]})
    assert response.status_code == 404
    job = Job(title="Other job", created_by=a["hr"].id, tenant_id=a["company"].id)
    db_session.add(job)
    await db_session.flush()
    other.job_id = job.id
    resume = Resume(candidate_id=other.candidate_id, tenant_id=other.tenant_id, file_url="http://test/other.pdf")
    db_session.add(resume)
    await db_session.flush()
    other.resume_id = resume.id
    await db_session.commit()
    for endpoint in ("compare", "batches"):
        response = await client.post(
            f"/api/v1/dossiers/{endpoint}",
            headers=headers,
            json={"application_ids": [str(a["application"].id), str(other.id)]},
        )
        assert response.status_code == 422 and response.json()["detail"] == "same_job_required"


async def test_versions_are_tenant_scoped_and_original_job_is_preserved(client, db_session, dossier, two_orgs):
    import copy
    from app.core.dossier_repository import record_analysis_version

    a = dossier
    appid = a["application"].id
    await record_analysis_version(
        db_session, a["application"], a["resume"], {"title": "Original job"}, {"matching": {"score": 50}}, {}
    )
    await db_session.commit()
    result = await client.get(f"/api/v1/dossiers/{appid}/versions", headers=auth_headers(a["hr"]))
    assert result.status_code == 200 and len(result.json()["items"]) == 1
    from app.models import DossierAnalysisVersion
    from sqlalchemy import select

    version = (await db_session.execute(select(DossierAnalysisVersion))).scalar_one()
    assert version.payload["job_context"]["title"] == "Original job"
    first_id = version.id
    updated = copy.deepcopy(a["resume"].parsed_data)
    updated["structured"]["identity"]["name"]["value"] = "Mira Hart revised"
    updated["_evidence_analysis"]["job_sha256"] = "changed-job-policy"
    a["resume"].parsed_data = updated
    await record_analysis_version(
        db_session, a["application"], a["resume"], {"title": "Updated job"}, {"matching": {"score": 90}}, {}
    )
    await db_session.commit()
    versions = (await db_session.execute(select(DossierAnalysisVersion))).scalars().all()
    new_id = next(v.id for v in versions if v.id != first_id)
    comparison = await client.get(
        f"/api/v1/dossiers/{appid}/versions/compare",
        params={"left": str(first_id), "right": str(new_id)},
        headers=auth_headers(a["hr"]),
    )
    assert comparison.status_code == 200, comparison.text
    data = comparison.json()
    assert not data["comparable"] and data["score_delta"] is None
    name = next(c for c in data["field_changes"] if c["field"] == "identity.name")
    assert name["before"]["value"] == "MIRA HART" and name["after"]["value"] == "Mira Hart revised"
    assert (
        await client.get(f"/api/v1/dossiers/{appid}/versions", headers=auth_headers(two_orgs["B"]["hr"]))
    ).status_code == 404


async def test_account_deletion_clears_review_history_and_fences_worker(client, db_session, dossier):
    from sqlalchemy import select
    from app.models import DossierReviewEvent, DossierReviewHead, DossierAnalysisVersion, DossierReanalysisBatch
    from app.core.dossier_repository import record_analysis_version

    a = dossier
    appid = a["application"].id
    await client.post(
        f"/api/v1/dossiers/{appid}/events",
        headers=auth_headers(a["hr"]),
        json=dict(
            action="note",
            expected_revision=0,
            reason="Synthetic private note",
            visibility="private",
            value="Sensitive fixture",
        ),
    )
    await record_analysis_version(db_session, a["application"], a["resume"], {"title": "fixture"}, {}, {})
    a["resume"].processing_state = dict(status="processing", attempt_id="old-attempt")
    a["resume"].agent_analysis = {"synthetic": "personal fixture"}
    batch = DossierReanalysisBatch(
        tenant_id=a["company"].id,
        actor_id=a["hr"].id,
        job_id=a["job"].id,
        payload={"items": {str(appid): {"enqueued": True}}},
    )
    db_session.add(batch)
    await db_session.commit()
    response = await client.delete("/api/v1/candidates/me/", headers=auth_headers(a["candidate_user"]))
    assert response.status_code == 200, response.text
    await db_session.refresh(a["resume"])
    assert a["resume"].agent_analysis is None and a["resume"].parsed_data is None
    assert a["resume"].processing_state["attempt_id"] != "old-attempt"
    assert a["resume"].processing_state["stage"] == "privacy"
    for model in (DossierReviewEvent, DossierReviewHead, DossierAnalysisVersion):
        assert not (await db_session.execute(select(model).where(model.application_id == appid))).scalars().all()
    await db_session.refresh(batch)
    assert str(appid) not in batch.payload["items"]


async def test_dispatch_crash_is_durable_and_recovery_is_bounded_owner_only(
    client, db_session, dossier, monkeypatch, make_user
):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.models import DossierReanalysisBatch
    from app.routers import dossier_review

    a = dossier
    dispatch = dossier_review.dispatch_batch
    monkeypatch.setattr(dossier_review, "dispatch_batch", AsyncMock(side_effect=RuntimeError("synthetic crash")))
    with pytest.raises(RuntimeError, match="synthetic crash"):
        await client.post(
            "/api/v1/dossiers/batches",
            headers=auth_headers(a["hr"]),
            json={"application_ids": [str(a["application"].id)]},
        )
    batch = (await db_session.execute(select(DossierReanalysisBatch))).scalar_one()
    batch_id = batch.id
    claim = batch.payload["items"][str(a["application"].id)]["queue_claim"]
    await db_session.refresh(a["resume"])
    assert a["resume"].processing_state["queue_claim"] == claim
    monkeypatch.setattr(dossier_review, "dispatch_batch", dispatch)
    enqueue = AsyncMock(return_value=None)
    monkeypatch.setattr(dossier_review, "enqueue_task", enqueue)
    other = await make_user(role="HR_Manager", tenant=a["company"])
    path = f"/api/v1/dossiers/batches/{batch_id}/recover"
    assert (await client.post(path, headers=auth_headers(other))).status_code == 404
    for _ in range(5):
        response = await client.post(path, headers=auth_headers(a["hr"]))
        assert response.status_code == 202, response.text
    assert enqueue.await_count == 3
    assert all(c.kwargs["job_id"] == claim for c in enqueue.await_args_list)
    state = (await client.get(f"/api/v1/dossiers/batches/{batch_id}", headers=auth_headers(a["hr"]))).json()
    assert not state["can_recover"]
    assert "queue_claim" not in state["items"][0]["queue"]


async def test_unknown_dispatch_result_reuses_claim_and_preserves_later_worker_result(
    client, db_session, dossier, monkeypatch
):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.models import DossierReanalysisBatch
    from app.routers import dossier_review

    a = dossier
    enqueue = AsyncMock(side_effect=RuntimeError("lost response"))
    monkeypatch.setattr(dossier_review, "enqueue_task", enqueue)
    with pytest.raises(RuntimeError, match="lost response"):
        await client.post(
            "/api/v1/dossiers/batches",
            headers=auth_headers(a["hr"]),
            json={"application_ids": [str(a["application"].id)]},
        )
    batch = (await db_session.execute(select(DossierReanalysisBatch))).scalar_one()
    claim = batch.payload["items"][str(a["application"].id)]["queue_claim"]
    enqueue.side_effect = None
    enqueue.return_value = claim
    path = f"/api/v1/dossiers/batches/{batch.id}/recover"
    response = await client.post(path, headers=auth_headers(a["hr"]))
    assert response.status_code == 202, response.text
    assert response.json()["items"][str(a["application"].id)]["enqueued"]
    await db_session.refresh(a["resume"])
    a["resume"].processing_state = dict(a["resume"].processing_state, status="succeeded", stage="complete")
    await db_session.commit()
    await client.post(path, headers=auth_headers(a["hr"]))
    assert enqueue.await_count == 2
    await db_session.refresh(a["resume"])
    assert a["resume"].processing_state["status"] == "succeeded"
