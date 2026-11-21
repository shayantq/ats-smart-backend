"""اجرای مستقل مدل با ذخیرهٔ مرحله‌ای، قفل کوتاه و محافظت از تلاش‌های قدیمی."""

import asyncio
import hashlib
import time
import uuid
from datetime import datetime, timezone

from rq import get_current_job
from rq.timeouts import JobTimeoutException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.text_extraction import UnreadableResumeFileError
from app.model_inference.client import InferenceError
from app.models import Application, Resume
from app.core.dossier_repository import record_analysis_version
from app.core.pdf_layout import EXTRACTION_VERSION
from app.core.structured_resume import PARSER_VERSION


class ResumeProcessingError(Exception):
    """فقط کد ثابت؛ خطای اصلی و دادهٔ شخصی وارد RQ نمی‌شود."""

    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.retryable = retryable


class StaleAttempt(Exception):
    """تلاش جدیدتر مالک رکورد است؛ تلاش قدیمی حق نوشتن ندارد."""


def now() -> float:
    return datetime.now(timezone.utc).timestamp()


def public_state(state: dict | None) -> dict | None:
    """فقط فیلدهای مجاز منتشر می‌شوند؛ lease منقضی به معنی پردازش زنده نیست."""
    if not state:
        return None
    result = {key: state.get(key) for key in ("status", "stage", "attempt", "updated_at", "error_code")}
    if state.get("status") in ("processing", "retrying") and state.get("expires_at", float("inf")) < now():
        result.update(status="failed", error_code="processing_expired")
    return result


async def run_model_job(application_id, file_url, session_factory, download):
    from app.core.config import settings
    from app.model_inference.limits import fetch_limits
    from app.core.analysis_evidence import VERSION as analysis_version, job_signature
    from app.agents.supervisor import to_skill_analysis
    from app.model_inference.pipeline import MODEL_EVIDENCE_POLICY_VERSION, run_model_pipeline
    from app.model_inference.resume_digest import cache_key
    from app.tasks.resume_processing import _load_job_context

    raw_input = settings.RESUME_MODEL_INPUT == "raw"
    if not raw_input:
        analysis_version = f"{analysis_version}/{MODEL_EVIDENCE_POLICY_VERSION}"
    if settings.MODEL_EVIDENCE_CHECK_ENABLED:
        analysis_version = f"{analysis_version}/evidence-check-v2"
    application_id = uuid.UUID(application_id)
    attempt_id = str(uuid.uuid4())
    job = get_current_job()
    queued, started_at = getattr(job, "enqueued_at", None), getattr(job, "started_at", None)
    queue_wait = None
    if isinstance(queued, datetime) and isinstance(started_at, datetime):

        def utc(value):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        queue_wait = max(0, (utc(started_at) - utc(queued)).total_seconds() * 1000)
    metrics = dict(
        queue_wait_ms=queue_wait,
        engine_prompt_tokens=None,
        engine_output_tokens=None,
        prefill_ms=None,
        generation_ms=None,
        engine_total_ms=None,
    )
    limits_task = None
    stage = "loading"
    async with session_factory() as db:
        application = await db.get(Application, application_id)
        if application is None or application.resume_id is None:
            raise ResumeProcessingError("application_missing")
        resume = (
            await db.execute(
                select(Resume)
                .where(
                    Resume.id == application.resume_id,
                    Resume.file_url == file_url,
                    Resume.candidate_id == application.candidate_id,
                    Resume.tenant_id == application.tenant_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if resume is None:
            raise ResumeProcessingError("resume_missing")
        previous = dict(resume.processing_state or {})
        # قفل ردیف فقط هنگام تصاحب/نوشتن باز است؛ OCR و شبکه خارج از تراکنش‌اند.
        if previous.get("status") == "processing" and previous.get("expires_at", 0) > now():
            raise ResumeProcessingError("attempt_already_running")
        resume_id = resume.id
        context = await _load_job_context(db, str(application_id), resume)
        context_signature = job_signature(context)
        cached_text, cached_parsed = resume.raw_text, resume.parsed_data
        state = dict(
            previous,
            status="processing",
            stage=stage,
            attempt_id=attempt_id,
            attempt=previous.get("attempt", 0) + 1,
            updated_at=now(),
            expires_at=now() + settings.RESUME_JOB_TIMEOUT_SECONDS + settings.RESUME_EXTRACTION_PARSE_ALLOWANCE_SECONDS,
            error_code=None,
        )
        resume.processing_state = state
        await db.commit()

    async def write(**changes):
        async with session_factory() as db:
            record = (await db.execute(select(Resume).where(Resume.id == resume_id).with_for_update())).scalar_one()
            current = record.processing_state or {}
            if current.get("attempt_id") != attempt_id:
                raise StaleAttempt()
            if changes.pop("clear_analysis", False):
                record.agent_analysis = None
                record.skill_analysis = None
                application = await db.get(Application, application_id)
                if application and application.resume_id == resume_id:
                    application.score_ai = None
            if "raw_text" in changes:
                record.raw_text = changes.pop("raw_text")
            if "parsed_data" in changes:
                record.parsed_data = changes.pop("parsed_data")
            record.processing_state = dict(current, **changes, updated_at=now(), metrics=dict(metrics))
            await db.commit()

    async def persist(text, parsed, next_stage, timings):
        nonlocal stage
        metrics.update(timings)
        stage = next_stage
        values = {
            "raw_text": text,
            "stage": stage,
            "file_sha256": digest,
            "cache_version": 1,
            "extraction_version": EXTRACTION_VERSION,
        }
        if parsed is not None:
            values["parsed_data"] = parsed
        values["parser_version"] = PARSER_VERSION if next_stage == "inference" else None
        if next_stage == "inference":
            values["force_reparse"] = False
        values.update(analysis_version=analysis_version, job_sha256=context_signature)
        if input_key != "raw" or "model_input_key" in previous:
            values["model_input_key"] = input_key
        await write(**values)

    def resolve_limits():
        nonlocal input_key
        limits = limits_task.result() if limits_task and limits_task.done() and not limits_task.cancelled() else None
        input_key = cache_key(
            settings.RESUME_MODEL_INPUT,
            cap=settings.RESUME_DIGEST_DESCRIPTION_CAP,
            icon_fonts=settings.RESUME_DIGEST_ICON_FONTS,
            context=limits.context_limit if limits else settings.MODEL_INFERENCE_CONTEXT_LIMIT,
            output=limits.output_limit if limits else settings.MODEL_INFERENCE_OUTPUT_LIMIT,
            tokenizer=settings.MODEL_INFERENCE_TOKENIZER_FILE,
        )
        if limits and settings.RESUME_MODEL_INPUT == "digest_l2":
            input_key += ":" + limits.tokenizer_sha256
        return limits

    input_key = "raw"
    try:
        if not settings.MODEL_INFERENCE_URL:
            raise InferenceError("model_endpoint_missing", 500)
        if settings.MODEL_INFERENCE_LIMITS_SYNC:
            limits_task = asyncio.create_task(fetch_limits())
        started = time.perf_counter()
        content = await asyncio.to_thread(download, file_url)
        metrics["file_loading_ms"] = (time.perf_counter() - started) * 1000
        digest = hashlib.sha256(content).hexdigest()
        same_file = previous.get("file_sha256") == digest
        cached_layout = (cached_parsed or {}).get("_extraction") or {}
        reusable = (
            same_file
            and cached_text is not None
            and previous.get("extraction_version") == EXTRACTION_VERSION
            and cached_layout.get("version") == EXTRACTION_VERSION
            and cached_layout.get("file_sha256") == digest
        )
        parsed_reusable = (
            reusable and previous.get("parser_version") == PARSER_VERSION and not previous.get("force_reparse")
        )
        resolve_limits()
        if (
            parsed_reusable
            and previous.get("status") == "succeeded"
            and previous.get("analysis_version") == analysis_version
            and previous.get("job_sha256") == context_signature
            and previous.get("model_input_key", "raw") == input_key
        ):
            metrics.update(previous.get("metrics") or {})
            metrics["queue_wait_ms"] = queue_wait
            await write(status="succeeded", stage="complete")
            return
        if not same_file:
            await write(raw_text=None, parsed_data=None, file_sha256=digest, clear_analysis=True)
        elif (previous.get("job_sha256") and previous["job_sha256"] != context_signature) or (
            not raw_input and previous.get("analysis_version") != analysis_version
        ):
            await write(clear_analysis=True)
        stage = "extraction"
        await write(stage=stage)
        result = await run_model_pipeline(
            content,
            file_url,
            context,
            saved_text=cached_text if reusable else None,
            saved_parsed=cached_parsed if parsed_reusable else None,
            saved_layout=(cached_parsed or {}).get("_extraction") if reusable else None,
            persist=persist,
            **({"resolve_limits": resolve_limits} if limits_task else {}),
        )
        metrics.update(result.metrics or {})
        stage = "commit"
        started = time.perf_counter()
        async with session_factory() as db:
            resume = (await db.execute(select(Resume).where(Resume.id == resume_id).with_for_update())).scalar_one()
            if (resume.processing_state or {}).get("attempt_id") != attempt_id:
                raise StaleAttempt()
            resume.agent_analysis = result.analysis.model_dump(mode="json")
            resume.skill_analysis = to_skill_analysis(result.analysis)
            application = await db.get(Application, application_id)
            if application.resume_id != resume_id:
                raise StaleAttempt()
            if result.analysis.matching.score is not None:
                application.score_ai = round(result.analysis.matching.score)
            elif metrics.get("model_score_suppressed"):
                application.score_ai = None
            await record_analysis_version(db, application, resume, context, resume.agent_analysis, dict(metrics))
            resume.processing_state = dict(
                resume.processing_state,
                status="succeeded",
                stage="complete",
                updated_at=now(),
                error_code=None,
                metrics=dict(metrics),
            )
            await db.commit()
        metrics["database_commit_ms"] = (time.perf_counter() - started) * 1000
        await write(status="succeeded", stage="complete")
    except StaleAttempt:
        raise ResumeProcessingError("stale_attempt") from None
    except Exception as error:
        if isinstance(error, InferenceError):
            code, retryable = error.code, error.retryable
        elif isinstance(error, UnreadableResumeFileError):
            code, retryable = "unreadable_resume", False
        elif isinstance(error, FileNotFoundError):
            code, retryable = "file_missing", False
        elif isinstance(error, JobTimeoutException):
            code, retryable = "job_timeout", True
        elif isinstance(error, (OSError, OperationalError)):
            code, retryable = "infrastructure_unavailable", True
        else:
            code, retryable = "processing_internal_error", False
        retries = bool(job and job.retries_left and retryable)
        if job and not retryable:
            job.retries_left = 0
        try:
            await write(
                status="retrying" if retries else "failed",
                stage=stage,
                error_code=code,
                expires_at=now() + 900 if retries else now(),
            )
        except StaleAttempt:
            pass
        except Exception:
            # در قطع دیتابیس، انقضای lease مانع نمایش دائمی «در حال پردازش» می‌شود.
            pass
        raise ResumeProcessingError(code, retryable) from None
    finally:
        if limits_task:
            limits_task.cancel()
            await asyncio.gather(limits_task, return_exceptions=True)
