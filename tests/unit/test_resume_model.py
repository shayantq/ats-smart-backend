"""رگرسیون ذخیرهٔ مرحله‌ای، تلاش مجدد و جلوگیری از نوشتن تلاش قدیمی."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import Application
from app.model_inference.client import InferenceError
from app.core.text_extraction import UnreadableResumeFileError
from app.tasks import resume_model as worker
from tests.unit.test_model_inference import map_analysis, response

APP_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def context(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MODEL_INFERENCE_URL", "http://local.invalid")
    monkeypatch.setattr(worker, "record_analysis_version", AsyncMock())
    resume = SimpleNamespace(
        id="r",
        raw_text=None,
        parsed_data=None,
        processing_state=None,
        candidate_id="c",
        tenant_id="t",
        agent_analysis=None,
    )
    application = SimpleNamespace(resume_id="r", candidate_id="c", tenant_id="t", score_ai=None, current_status="Draft")
    commits = []
    job = SimpleNamespace(retries_left=2)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, model, identifier):
            return application if model is Application else resume

        async def execute(self, query):
            return SimpleNamespace(scalar_one=lambda: resume, scalar_one_or_none=lambda: resume)

        async def commit(self):
            commits.append(copy.deepcopy(vars(resume)))

    monkeypatch.setattr(worker, "get_current_job", lambda: job)
    monkeypatch.setattr("app.tasks.resume_processing._load_job_context", AsyncMock(return_value={"title": "Test"}))
    return SimpleNamespace(resume=resume, application=application, session=Session, commits=commits, job=job)


@pytest.mark.parametrize(
    "error,status,retry",
    [
        (InferenceError("engine_unavailable", 503), "retrying", 2),
        (InferenceError("context_limit_exceeded", 422), "failed", 0),
        (UnreadableResumeFileError(), "failed", 0),
    ],
)
async def test_failed_analysis_is_not_success_and_keeps_committed_text(context, monkeypatch, error, status, retry):
    async def pipeline(*args, persist, **kwargs):
        await persist("synthetic", {"skills": []}, "inference", {"extraction_ms": 1})
        assert context.commits[-1]["raw_text"] == "synthetic"
        raise error

    monkeypatch.setattr("app.model_inference.pipeline.run_model_pipeline", pipeline)
    with pytest.raises(worker.ResumeProcessingError):
        await worker.run_model_job(APP_ID, "test.pdf", context.session, lambda _: b"test")
    assert context.resume.raw_text == "synthetic"
    assert context.resume.parsed_data == {"skills": []}
    assert context.resume.processing_state["status"] == status
    assert context.job.retries_left == retry
    assert context.resume.agent_analysis is None
    assert context.application.current_status == "Draft"


async def test_success_is_idempotent_for_same_file(context, monkeypatch):
    calls = []

    async def pipeline(*args, persist, **kwargs):
        calls.append(1)
        import hashlib

        await persist(
            "synthetic",
            {"_extraction": {"version": 2, "file_sha256": hashlib.sha256(b"test").hexdigest()}},
            "inference",
            {},
        )
        return SimpleNamespace(analysis=map_analysis(response(), "synthetic", {}, 1), metrics={})

    monkeypatch.setattr("app.model_inference.pipeline.run_model_pipeline", pipeline)
    for _ in range(2):
        await worker.run_model_job(APP_ID, "test.pdf", context.session, lambda _: b"test")
    assert len(calls) == 1
    assert context.resume.processing_state["status"] == "succeeded"
    assert context.application.score_ai == 70
    assert context.commits[-1]["agent_analysis"] is not None


async def test_stale_attempt_cannot_overwrite_newer_analysis(context, monkeypatch):
    async def pipeline(*args, persist, **kwargs):
        await persist("synthetic", {}, "inference", {})
        context.resume.processing_state = {"attempt_id": "newer", "status": "succeeded"}
        context.resume.agent_analysis = {"marker": "newer"}
        return SimpleNamespace(analysis=map_analysis(response(), "synthetic", {}, 1), metrics={})

    monkeypatch.setattr("app.model_inference.pipeline.run_model_pipeline", pipeline)
    with pytest.raises(worker.ResumeProcessingError, match="stale_attempt"):
        await worker.run_model_job(APP_ID, "test.pdf", context.session, lambda _: b"test")
    assert context.resume.agent_analysis == {"marker": "newer"}
    assert context.resume.processing_state["attempt_id"] == "newer"


def test_expired_worker_is_not_presented_as_live_and_internal_fields_are_hidden():
    state = worker.public_state(
        {"status": "processing", "expires_at": 0, "attempt_id": "private", "file_sha256": "private"}
    )
    assert state["status"] == "failed"
    assert state["error_code"] == "processing_expired"
    assert "attempt_id" not in state and "file_sha256" not in state


def test_failure_before_claim_is_sanitized_and_not_marked_success(monkeypatch):
    from app.tasks import resume_processing
    from app.core.config import settings

    monkeypatch.setattr(settings, "RESUME_PIPELINE", "model")
    monkeypatch.setattr(resume_processing, "_run_job", AsyncMock(side_effect=ValueError("private file or SQL data")))
    with pytest.raises(worker.ResumeProcessingError, match="^processing_internal_error$") as caught:
        resume_processing.process_resume_task(APP_ID, "private-file.pdf")
    assert caught.value.__suppress_context__


async def test_phase3_reparses_old_success_without_repeating_extraction(context, monkeypatch):
    import hashlib

    digest = hashlib.sha256(b"test").hexdigest()
    layout = {"version": 2, "file_sha256": digest}
    context.resume.raw_text = "synthetic"
    context.resume.parsed_data = {"_extraction": layout, "old": True}
    context.resume.processing_state = {
        "status": "succeeded",
        "file_sha256": digest,
        "extraction_version": 2,
        "parser_version": 3,
    }
    calls = []

    async def pipeline(*args, persist, **kwargs):
        calls.append(kwargs)
        await persist("synthetic", {"_extraction": layout}, "inference", {})
        return SimpleNamespace(analysis=map_analysis(response(), "synthetic", {}, 1), metrics={})

    monkeypatch.setattr("app.model_inference.pipeline.run_model_pipeline", pipeline)
    await worker.run_model_job(APP_ID, "test.pdf", context.session, lambda _: b"test")
    assert len(calls) == 1
    assert calls[0]["saved_text"] == "synthetic"
    assert calls[0]["saved_parsed"] is None
    assert calls[0]["saved_layout"] == layout
    assert context.resume.processing_state["parser_version"] == 6


async def test_changed_job_does_not_reuse_completed_analysis(context, monkeypatch):
    import hashlib

    monkeypatch.setattr(
        "app.tasks.resume_processing._load_job_context",
        AsyncMock(
            side_effect=[
                {"title": "Test", "skills_required": ["Python"]},
                {"title": "Test", "skills_required": ["Java"]},
            ]
        ),
    )
    calls = []

    async def pipeline(*args, persist, **kwargs):
        calls.append(kwargs)
        await persist(
            "synthetic",
            {"_extraction": {"version": 2, "file_sha256": hashlib.sha256(b"test").hexdigest()}},
            "inference",
            {},
        )
        return SimpleNamespace(analysis=map_analysis(response(), "synthetic", {}, 1), metrics={})

    monkeypatch.setattr("app.model_inference.pipeline.run_model_pipeline", pipeline)
    for _ in range(2):
        await worker.run_model_job(APP_ID, "test.pdf", context.session, lambda _: b"test")
    assert len(calls) == 2
    assert calls[1]["saved_text"] == "synthetic"
    assert any(
        snapshot.get("agent_analysis") is None and snapshot["processing_state"].get("attempt") == 2
        for snapshot in context.commits
    )
