"""خواندن محدود به درخواست/سازمان و ثبت رویداد با قفل نسخهٔ کوتاه."""

from fastapi import HTTPException
from sqlalchemy import select, or_, func
from sqlalchemy.dialects.postgresql import insert

from app.core.dossier_review import digest, replay, source_hash, target_fact, snapshot_payload
from app.models import Application, Resume, DossierReviewHead, DossierReviewEvent, DossierAnalysisVersion


async def linked_resume(db, application_id, lock=False):
    query = select(Application).where(Application.id == application_id)
    application = (await db.execute(query)).scalar_one_or_none()
    if application is None or application.resume_id is None:
        raise HTTPException(404, "dossier_missing")
    query = select(Resume).where(
        Resume.id == application.resume_id,
        Resume.tenant_id == application.tenant_id,
        Resume.candidate_id == application.candidate_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    resume = (await db.execute(query)).scalar_one_or_none()
    if resume is None or resume.file_url.startswith("deleted:"):
        raise HTTPException(404, "dossier_missing")
    if lock:
        current = (
            await db.execute(
                select(Application)
                .where(Application.id == application_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if current.resume_id != resume.id:
            raise HTTPException(409, "dossier_source_changed")
    return application, resume


def event_data(event, user_id):
    return dict(
        id=str(event.id),
        action=event.action,
        visibility=event.visibility,
        own=event.actor_id == user_id,
        created_at=event.created_at.isoformat(),
        resume_id=str(event.resume_id),
        payload=event.payload,
    )


async def review_state(db, application_id, user):
    application, resume = await linked_resume(db, application_id)
    head = (
        await db.execute(select(DossierReviewHead).where(DossierReviewHead.application_id == application_id))
    ).scalar_one_or_none()
    rows = list(
        (
            await db.execute(
                select(DossierReviewEvent)
                .where(
                    DossierReviewEvent.application_id == application_id,
                    or_(DossierReviewEvent.visibility == "team", DossierReviewEvent.actor_id == user.id),
                )
                .order_by(DossierReviewEvent.sequence)
                .limit(501)
            )
        ).scalars()
    )
    if len(rows) > 500:
        raise HTTPException(409, "review_history_limit")
    events = [event_data(e, user.id) for e in rows]
    result = replay(resume.parsed_data, events)
    targets = []
    parsed = resume.parsed_data or {}
    names = ["identity.name", "identity.location"]
    for record in (parsed.get("structured") or {}).get("activities", []):
        names += [
            f"activity:{record['id']}:{key}"
            for key in record["fields"]
            if key in {"job_title", "company", "duration", "location", "client", "engagement_type"}
        ]
    for target in names:
        fact, anchor = target_fact(parsed, target)
        if fact is not None:
            targets.append(dict(target=target, original=fact, anchor=anchor))
    return dict(
        result,
        application_id=str(application_id),
        revision=head.revision if head else 0,
        source_hash=source_hash(parsed),
        targets=targets,
        events=events,
    )


async def append_review(db, application_id, user, data):
    application, resume = await linked_resume(db, application_id, lock=True)
    await db.execute(
        insert(DossierReviewHead)
        .values(application_id=application_id, tenant_id=application.tenant_id, revision=0)
        .on_conflict_do_nothing()
    )
    head = (
        await db.execute(
            select(DossierReviewHead).where(DossierReviewHead.application_id == application_id).with_for_update()
        )
    ).scalar_one()
    if data.visibility == "team" and data.expected_revision != head.revision:
        raise HTTPException(409, "review_revision_conflict")
    if head.revision >= 400:
        raise HTTPException(409, "review_history_limit")
    if data.visibility == "private":
        count = (
            await db.execute(
                select(func.count())
                .select_from(DossierReviewEvent)
                .where(
                    DossierReviewEvent.application_id == application_id,
                    DossierReviewEvent.actor_id == user.id,
                    DossierReviewEvent.visibility == "private",
                )
            )
        ).scalar_one()
        if count >= 100:
            raise HTTPException(409, "private_note_limit")
    if data.action in {"correction", "revoke"}:
        original, anchor = target_fact(resume.parsed_data, data.target)
        if original is None or anchor != data.anchor or data.source_hash != source_hash(resume.parsed_data):
            raise HTTPException(409, "review_source_changed")
    if data.action == "section_review" and data.source_hash != source_hash(resume.parsed_data):
        raise HTTPException(409, "review_source_changed")
    payload = data.model_dump(exclude={"expected_revision", "action", "visibility"})
    parsed = resume.parsed_data or {}
    profile = parsed.get("_evidence_analysis") or {}
    payload.update(
        source_hash=source_hash(parsed),
        analysis_version=profile.get("version"),
        job_sha256=profile.get("job_sha256"),
        analysis_fingerprint=digest(parsed),
    )
    event = DossierReviewEvent(
        application_id=application.id,
        resume_id=resume.id,
        tenant_id=application.tenant_id,
        actor_id=user.id,
        action=data.action,
        visibility=data.visibility,
        payload=payload,
    )
    db.add(event)
    if data.visibility == "team":
        head.revision += 1
    await db.commit()
    return await review_state(db, application_id, user)


async def record_analysis_version(db, application, resume, context, analysis, metrics):
    payload = snapshot_payload(resume, context, analysis, metrics)
    # زمان و metrics تصادفی نسخهٔ یکسان را به نسخهٔ تازه تبدیل نمی‌کنند.
    fingerprint = digest({k: v for k, v in payload.items() if k != "metrics"})
    exists = (
        await db.execute(
            select(DossierAnalysisVersion.id).where(
                DossierAnalysisVersion.application_id == application.id,
                DossierAnalysisVersion.fingerprint == fingerprint,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(
            DossierAnalysisVersion(
                application_id=application.id,
                resume_id=resume.id,
                tenant_id=application.tenant_id,
                fingerprint=fingerprint,
                payload=payload,
            )
        )
