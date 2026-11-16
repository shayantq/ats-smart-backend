"""بازیابی محدود outbox گروه؛ فقط claim پایدار و همان نویسنده قابل ارسال مجدد است."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.core.dossier_repository import linked_resume
from app.models import DossierReanalysisBatch
from app.tasks.resume_processing import process_resume_task

PENDING = {"dispatch_pending", "queue_unavailable"}
MAX_DISPATCH_ATTEMPTS = 3


def public_item(item):
    return dict(
        enqueued=bool(item.get("enqueued")),
        reason=item.get("reason"),
        dispatch_attempts=item.get("dispatch_attempts", 0),
        recoverable=bool(
            item.get("queue_claim")
            and item.get("reason") in PENDING
            and item.get("dispatch_attempts", 0) < MAX_DISPATCH_ATTEMPTS
        ),
    )


async def load_batch(db, batch_id, user, lock=False):
    query = select(DossierReanalysisBatch).where(
        DossierReanalysisBatch.id == batch_id, DossierReanalysisBatch.actor_id == user.id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = (await db.execute(query)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, "batch_missing")
    return batch


async def dispatch_batch(db, batch_id, user, enqueue):
    batch = await load_batch(db, batch_id, user)
    identifiers = list(batch.payload.get("items", {}))
    if len(identifiers) > 20:
        raise HTTPException(409, "batch_limit_exceeded")
    for identifier in identifiers:
        try:
            application, resume = await linked_resume(db, uuid.UUID(identifier), lock=True)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            await db.rollback()
            continue
        batch = await load_batch(db, batch_id, user, lock=True)
        items = dict(batch.payload.get("items", {}))
        item = dict(items.get(identifier, {}))
        state = resume.processing_state or {}
        claim = item.get("queue_claim")
        valid = (
            item.get("reason") in PENDING
            and claim
            and claim == state.get("queue_claim")
            and state.get("queue_batch") == str(batch_id)
            and (
                state.get("status") == "queued"
                or (state.get("status") == "failed" and state.get("error_code") == "queue_unavailable")
            )
        )
        if not valid or item.get("dispatch_attempts", 0) >= MAX_DISPATCH_ATTEMPTS:
            if not valid and item.get("reason") in PENDING and claim:
                observed = claim == state.get("queue_claim") and state.get("queue_batch") == str(batch_id)
                item.update(
                    enqueued=bool(observed), reason="observed_" + str(state.get("status")) if observed else "superseded"
                )
                items[identifier] = item
                batch.payload = {"items": items}
            await db.commit()
            continue
        # قصد ارسال قبل از تماس Redis پایدار می‌شود؛ قطع فرایند قابل مشاهده می‌ماند.
        item["dispatch_attempts"] = item.get("dispatch_attempts", 0) + 1
        items[identifier] = item
        batch.payload = {"items": items}
        file_url = resume.file_url
        await db.commit()
        job_id = await enqueue(
            process_resume_task, str(application.id), file_url, job_id=claim, description="resume_reanalysis"
        )
        try:
            _, resume = await linked_resume(db, uuid.UUID(identifier), lock=True)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            await db.rollback()
            continue
        batch = await load_batch(db, batch_id, user, lock=True)
        items = dict(batch.payload.get("items", {}))
        current = dict(items.get(identifier, {}))
        if current.get("queue_claim") != claim:
            await db.commit()
            continue
        # پاسخ نامعلوم یک ارسال هم‌زمان نباید موفقیت ثبت‌شدهٔ قبلی را پس بگیرد.
        if not current.get("enqueued"):
            current.update(enqueued=bool(job_id), reason="queued" if job_id else "queue_unavailable")
        items[identifier] = current
        batch.payload = {"items": items}
        state = resume.processing_state or {}
        if (
            not job_id
            and not current.get("enqueued")
            and state.get("queue_claim") == claim
            and state.get("status") == "queued"
        ):
            resume.processing_state = dict(state, status="failed", error_code="queue_unavailable")
        elif (
            job_id
            and state.get("queue_claim") == claim
            and state.get("status") == "failed"
            and state.get("error_code") == "queue_unavailable"
        ):
            resume.processing_state = dict(state, status="queued", error_code=None)
        await db.commit()
    batch = await load_batch(db, batch_id, user, lock=True)
    result = dict(
        batch_id=str(batch.id),
        items={k: public_item(v) for k, v in batch.payload.get("items", {}).items()},
        message_sent=False,
    )
    await db.commit()
    return result
