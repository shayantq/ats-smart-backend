"""بازبینی انسانی، مقایسه و عملیات گروهی؛ بدون ارسال پیام به کارجو."""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles, get_current_user
from app.core.dossier_repository import linked_resume, review_state, append_review
from app.core.dossier_review import compare_payloads
from app.core.dossier_dispatch import dispatch_batch, public_item
from app.core.queue import enqueue_resume_once as enqueue_task
from app.db.session import get_db
from app.models import User, DossierAnalysisVersion, DossierReanalysisBatch
from app.schemas.dossier_review import ReviewEventInput, SelectionInput
from app.tasks.resume_model import public_state


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(require_roles("Admin", "HR_Manager")), Depends(private_response)])


async def selection(db, identifiers):
    if len(set(identifiers)) != len(identifiers):
        raise HTTPException(422, "duplicate_selection")
    selected = [await linked_resume(db, identifier) for identifier in identifiers]
    if len({a.job_id for a, _ in selected}) != 1:
        raise HTTPException(422, "same_job_required")
    return selected


@router.post("/compare")
async def compare_dossiers(
    body: SelectionInput, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if len(body.application_ids) > 10:
        raise HTTPException(422, "comparison_limit_ten")
    selected = await selection(db, body.application_ids)
    rows = []
    for application, resume in selected:
        reviewed = await review_state(db, application.id, user)
        parsed = reviewed["effective_parsed"]
        profile = parsed.get("_evidence_analysis") or {}
        state = public_state(resume.processing_state) or {}
        complete = (
            state.get("status") == "succeeded"
            and (parsed.get("_extraction") or {}).get("status") != "partial"
            and not parsed.get("_review_warning")
        )
        rows.append(
            dict(
                application_id=str(application.id),
                shortlisted=reviewed["shortlisted"],
                processing_state=state,
                complete=complete,
                analysis_version=profile.get("version"),
                job_sha256=profile.get("job_sha256"),
                weighting=(profile.get("coverage") or {}).get("weighting"),
                requirements=profile.get("requirements") or [],
                coverage=profile.get("coverage"),
                source_hash=(parsed.get("_extraction") or {}).get("file_sha256"),
            )
        )
    policies = {(r["analysis_version"], r["job_sha256"], r["weighting"]) for r in rows}
    comparable = len(policies) == 1 and all(r["complete"] and r["analysis_version"] and r["job_sha256"] for r in rows)
    return dict(
        items=rows,
        comparable=comparable,
        ranked=False,
        reason="same_policy" if comparable else "incomplete_or_different_policy",
        message_sent=False,
    )


@router.post("/batches", status_code=202)
async def create_batch(
    body: SelectionInput, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    selected = await selection(db, body.application_ids)
    first = selected[0][0]
    items = {str(identifier): dict(enqueued=False, reason="dispatch_pending") for identifier in body.application_ids}
    batch = DossierReanalysisBatch(
        tenant_id=first.tenant_id, actor_id=user.id, job_id=first.job_id, payload={"items": dict(items)}
    )
    db.add(batch)
    await db.flush()
    batch_id = batch.id
    # ترتیب قفل ثابت است؛ تمام قصدهای ارسال همراه گروه در یک تراکنش ثبت می‌شوند.
    for identifier in sorted(body.application_ids):
        application, resume = await linked_resume(db, identifier, lock=True)
        state = resume.processing_state or {}
        if state.get("status") in {"queued", "retrying"} or (
            state.get("status") == "processing" and state.get("expires_at", float("inf")) > time.time()
        ):
            items[str(identifier)] = dict(enqueued=False, reason="already_active")
            continue
        claim = str(uuid.uuid4())
        resume.processing_state = dict(
            state,
            force_reparse=True,
            status="queued",
            stage="queued",
            expires_at=time.time() + 900,
            queue_claim=claim,
            queue_batch=str(batch_id),
            updated_at=time.time(),
            error_code=None,
        )
        items[str(identifier)] = dict(enqueued=False, reason="dispatch_pending", queue_claim=claim, dispatch_attempts=0)
    batch.payload = {"items": items}
    await db.commit()
    return await dispatch_batch(db, batch_id, user, enqueue_task)


@router.post("/batches/{batch_id}/recover", status_code=202)
async def recover_batch(
    batch_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await dispatch_batch(db, batch_id, user, enqueue_task)


@router.get("/batches/{batch_id}")
async def batch_progress(
    batch_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    batch = (
        await db.execute(select(DossierReanalysisBatch).where(DossierReanalysisBatch.id == batch_id))
    ).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, "batch_missing")
    rows = []
    for identifier, queued in batch.payload.get("items", {}).items():
        try:
            _, resume = await linked_resume(db, uuid.UUID(identifier))
            rows.append(
                dict(
                    application_id=identifier,
                    queue=public_item(queued),
                    processing=public_state(resume.processing_state),
                )
            )
        except HTTPException:
            rows.append(
                dict(application_id=identifier, queue=public_item(queued), processing={"status": "unavailable"})
            )
    return dict(
        batch_id=str(batch.id),
        items=rows,
        can_recover=batch.actor_id == user.id
        and any(public_item(i)["recoverable"] for i in batch.payload.get("items", {}).values()),
    )


@router.get("/{application_id}/review")
async def get_review(
    application_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await review_state(db, application_id, user)


@router.post("/{application_id}/events")
async def add_review_event(
    application_id: uuid.UUID,
    body: ReviewEventInput,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await append_review(db, application_id, user, body)


@router.get("/{application_id}/versions")
async def list_versions(application_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await linked_resume(db, application_id)
    versions = (
        await db.execute(
            select(DossierAnalysisVersion)
            .where(DossierAnalysisVersion.application_id == application_id)
            .order_by(DossierAnalysisVersion.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return dict(
        items=[
            dict(
                id=str(v.id),
                created_at=v.created_at.isoformat(),
                source_hash=v.payload.get("source_hash"),
                analysis_version=v.payload.get("analysis_version"),
                job_sha256=v.payload.get("job_sha256"),
            )
            for v in versions
        ]
    )


@router.get("/{application_id}/versions/compare")
async def compare_versions(
    application_id: uuid.UUID, left: uuid.UUID, right: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    await linked_resume(db, application_id)
    rows = list(
        (
            await db.execute(
                select(DossierAnalysisVersion).where(
                    DossierAnalysisVersion.application_id == application_id,
                    DossierAnalysisVersion.id.in_([left, right]),
                )
            )
        ).scalars()
    )
    if len(rows) != (1 if left == right else 2):
        raise HTTPException(404, "version_missing")
    by_id = {v.id: v.payload for v in rows}
    return compare_payloads(by_id[left], by_id[right])
