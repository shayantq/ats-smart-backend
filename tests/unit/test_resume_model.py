"""رگرسیون ذخیرهٔ مرحله‌ای، تلاش مجدد و جلوگیری از نوشتن تلاش قدیمی."""

import asyncio
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import settings
from app.models import Application
from app.model_inference.client import InferenceError
from app.model_inference import pipeline
from app.model_inference.contract import VerifyEvidenceResponse
from app.model_inference.limits import GatewayLimits
from app.core.text_extraction import UnreadableResumeFileError
from app.tasks import resume_model as worker
from tests.unit.test_model_inference import map_analysis, response
from tests.unit.test_model_budget import LONG_SYNTHETIC

APP_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def context(monkeypatch):
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


@pytest.mark.parametrize("case", ["over_budget", "gateway_mismatch", "under_budget_and_cache", "encode_failure"])
async def test_worker_preflight(context, monkeypatch, caplog, case):
    source_text = LONG_SYNTHETIC if case == "over_budget" else "متن ساختگی نمونه برای آزمون."
    job_title = "عنوان آزمایشی ساختگی"
    job_context = {"title": job_title, "description": "شرح ساختگی آزمایشی"}
    file_bytes = b"synthetic file"
    layout = {"version": worker.EXTRACTION_VERSION, "file_sha256": hashlib.sha256(file_bytes).hexdigest()}
    structured = {"activities": []}
    evidence = {"requirements": []}
    calls = []
    real_client = pipeline.InferenceClient

    def handle(request):
        calls.append(json.loads(request.content))
        if case == "gateway_mismatch":
            return httpx.Response(
                422,
                json={"detail": "context_limit_exceeded", "debug": source_text},
                headers={"X-ATS-context-limit": "1024"},
            )
        return httpx.Response(200, json=response().model_dump())

    def client(*args, **kwargs):
        assert case != "over_budget"
        return real_client(*args, **kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    if case == "encode_failure":

        def broken_encode(prompt, *, add_special_tokens):
            raise RuntimeError(prompt)

        tokenizer = SimpleNamespace(encode=broken_encode)
        monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "configured")
        monkeypatch.setattr("app.model_inference.budget._load_tokenizer", lambda _: (tokenizer, "a" * 64))
        monkeypatch.setattr("app.model_inference.budget._warned_pid", None)
    monkeypatch.setattr(pipeline, "InferenceClient", client)
    monkeypatch.setattr(pipeline, "issue_service_token", lambda **_: "test-token")
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: dict(layout, raw_text=source_text))
    monkeypatch.setattr(
        pipeline,
        "parse_resume_text",
        lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda: {"structured": structured}),
    )
    monkeypatch.setattr("app.core.analysis_evidence.build_analysis", lambda *_: evidence)
    monkeypatch.setattr("app.tasks.resume_processing._load_job_context", AsyncMock(return_value=job_context))

    async def run():
        await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: file_bytes)

    if case in {"under_budget_and_cache", "encode_failure"}:
        await run()
        assert context.resume.processing_state["status"] == "succeeded"
        metrics = context.resume.processing_state["metrics"]
        assert metrics["method"] == "estimate"
        if case == "encode_failure":
            assert metrics["exact_count_failed"] == 1
            assert caplog.messages == ["RuntimeError"]
            assert source_text not in caplog.text
            assert "tokenizer_sha256" not in metrics
        else:
            assert "exact_count_failed" not in metrics
            monkeypatch.setattr(settings, "MODEL_INFERENCE_CONTEXT_LIMIT", 1)
            await run()
            assert context.resume.processing_state["status"] == "succeeded"
        assert len(calls) == 1
    else:
        expected = "input_exceeds_model_budget" if case == "over_budget" else "context_limit_exceeded"
        with pytest.raises(worker.ResumeProcessingError, match=f"^{expected}$") as caught:
            await run()
        state = context.resume.processing_state
        assert (state["status"], state["stage"], state["error_code"]) == ("failed", "inference", expected)
        assert not caught.value.retryable
        assert context.job.retries_left == 0
        metrics = state["metrics"]
        assert metrics["method"] == "estimate"
        assert context.commits[-2]["raw_text"] == source_text
        assert context.commits[-2]["parsed_data"]["_evidence_analysis"] == evidence
        assert (metrics["over_by"] > 0) == (case == "over_budget")
        assert metrics.get("preflight_gateway_mismatch", 0) == (case == "gateway_mismatch")
        if case == "gateway_mismatch":
            assert metrics["context_limit"] == 1024
            assert metrics["preflight_context_limit"] == settings.MODEL_INFERENCE_CONTEXT_LIMIT
        diagnostics = " ".join((str(caught.value), json.dumps(metrics, ensure_ascii=False), caplog.text))
        for sensitive in (source_text, job_title, job_context["description"], "synthetic.pdf", "test-token"):
            assert sensitive not in diagnostics

    assert context.resume.raw_text == source_text
    assert context.resume.parsed_data["structured"] == structured
    assert context.resume.parsed_data["_evidence_analysis"] == evidence
    if case == "over_budget":
        assert calls == []
    else:
        request = pipeline.AnalyzeRequest(resume_text=source_text, job=pipeline.JobContext(**job_context))
        assert calls == [request.model_dump()]


@pytest.mark.parametrize("mode", ["matching", "smaller_budget", "different_hash", "pending", "old_gateway"])
async def test_worker_applies_ready_limits_and_persists_numeric_timings(context, monkeypatch, mode):
    known = "a" * 64
    context.job.enqueued_at = datetime.now(timezone.utc)
    context.job.started_at = context.job.enqueued_at + timedelta(milliseconds=125)
    started = asyncio.Event()

    async def fetch():
        started.set()
        if mode == "pending":
            await asyncio.Event().wait()
        if mode == "old_gateway":
            return None
        return GatewayLimits(
            context_limit=641 if mode == "smaller_budget" else 2048,
            output_limit=640,
            tokenizer_sha256=("b" * 64 if mode == "different_hash" else known),
            parallel=1,
        )

    original_measure = pipeline.check_prompt_budget
    paths = []

    def measure(prompt, context_limit, output_limit, path):
        paths.append(path)
        return original_measure(prompt, context_limit, output_limit)

    class Client:
        def __init__(self, *unused, **kwargs):
            self.client = pipeline_client(*unused, **kwargs, transport=httpx.MockTransport(handle))

        async def __aenter__(self):
            return await self.client.__aenter__()

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

    def handle(request):
        assert request.url.path == "/v1/analyze"
        headers = (
            {}
            if mode == "old_gateway"
            else {
                "X-ATS-Time-Engine-Prompt-Tokens": "101",
                "X-ATS-Time-Engine-Prompt-Ms": "12.5",
                "X-ATS-Time-Engine-Predicted-Ms": "23.5",
            }
        )
        return httpx.Response(200, json=response().model_dump(), headers=headers)

    pipeline_client = pipeline.InferenceClient
    monkeypatch.setattr(settings, "MODEL_INFERENCE_LIMITS_SYNC", True)
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "configured")
    monkeypatch.setattr(pipeline, "configured_tokenizer_sha256", lambda _: known)
    monkeypatch.setattr(pipeline, "check_prompt_budget", measure)
    monkeypatch.setattr(pipeline, "InferenceClient", Client)
    monkeypatch.setattr(pipeline, "issue_service_token", lambda **_: "test-token")
    monkeypatch.setattr("app.model_inference.limits.fetch_limits", fetch)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_, **__: "synthetic resume")
    monkeypatch.setattr(pipeline, "parse_resume_text", lambda *_, **__: SimpleNamespace(model_dump=dict))

    async def run():
        await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")

    if mode == "smaller_budget":
        with pytest.raises(worker.ResumeProcessingError, match="input_exceeds_model_budget"):
            await run()
    else:
        await asyncio.wait_for(run(), timeout=1)
    assert started.is_set()
    metrics = context.resume.processing_state["metrics"]
    assert metrics["queue_wait_ms"] == 125
    assert metrics.get("limits_synced", 0) == int(mode not in {"pending", "old_gateway"})
    assert metrics.get("limits_mismatch", 0) == int(mode == "smaller_budget")
    assert metrics.get("tokenizer_hash_mismatch", 0) == int(mode == "different_hash")
    assert paths == ([""] if mode == "different_hash" else ["configured"])
    expected = (None, None, None, None) if mode in {"old_gateway", "smaller_budget"} else (101, 12.5, 23.5, 36)
    assert (
        tuple(metrics[key] for key in ("engine_prompt_tokens", "prefill_ms", "generation_ms", "engine_total_ms"))
        == expected
    )
    assert metrics["engine_output_tokens"] == (None if mode == "smaller_budget" else 200)


async def test_worker_digest_is_opt_in_and_cache_distinguishes_modes_and_versions(context, monkeypatch):
    from app.core.config import Settings
    from app.model_inference import resume_digest

    assert Settings.model_fields["RESUME_MODEL_INPUT"].default == "raw"
    file_bytes = b"synthetic file"
    source = "متن  ساختگی \u200fبرای ارزیابی"
    analyze = AsyncMock(return_value=response())

    class Client:
        def __init__(self, *args, **kwargs):
            self.analyze = analyze

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(pipeline, "InferenceClient", Client)
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(
        pipeline,
        "extract_raw_text",
        lambda *_args, **_kwargs: dict(
            raw_text=source, version=worker.EXTRACTION_VERSION, file_sha256=hashlib.sha256(file_bytes).hexdigest()
        ),
    )
    monkeypatch.setattr(pipeline, "parse_resume_text", lambda *_args, **_kwargs: SimpleNamespace(model_dump=dict))

    async def run(mode):
        monkeypatch.setattr(settings, "RESUME_MODEL_INPUT", mode)
        await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: file_bytes)
        return context.resume.processing_state

    original = await run("raw")
    assert analyze.call_args.args[0].resume_text == source
    assert "digest_level" not in original["metrics"] and "model_input_key" not in original
    l0 = await run("digest_l0")
    assert analyze.call_args.args[0].resume_text == "متن ساختگی برای ارزیابی"
    assert l0["metrics"]["digest_level"] == 0
    assert context.resume.raw_text == source
    l1 = await run("digest_l1")
    assert l1["model_input_key"] != l0["model_input_key"]
    await run("digest_l1")
    assert analyze.await_count == 3
    monkeypatch.setattr(resume_digest, "BUILDER_VERSION", resume_digest.BUILDER_VERSION + 1)
    new_version = await run("digest_l1")
    assert new_version["model_input_key"] != l1["model_input_key"]
    assert analyze.await_count == 4
    await run("raw")
    assert context.resume.processing_state["model_input_key"] == "raw"
    assert analyze.await_count == 5
    assert analyze.call_args.args[0].resume_text == source


async def test_worker_oversized_digest_fails_without_model_or_truncation(context, monkeypatch):
    source = LONG_SYNTHETIC + "\u200f"
    structured = {"activities": []}
    model = AsyncMock()
    monkeypatch.setattr(settings, "RESUME_MODEL_INPUT", "digest_l0")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(pipeline, "InferenceClient", model)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        pipeline,
        "parse_resume_text",
        lambda *_args, **_kwargs: SimpleNamespace(model_dump=lambda: {"structured": structured}),
    )
    monkeypatch.setattr("app.core.analysis_evidence.build_analysis", lambda *_: {"requirements": []})
    with pytest.raises(worker.ResumeProcessingError, match="^input_exceeds_model_budget$"):
        await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")
    model.assert_not_called()
    assert context.resume.raw_text == source
    assert context.resume.parsed_data["structured"] == structured
    metrics = context.resume.processing_state["metrics"]
    assert metrics["digest_level"] == 0
    assert metrics["digest_tokens"] == metrics["prompt_tokens"] > 1408
    assert metrics["unassigned_chars"] > 0 and metrics["omitted_chars"] == 0
    assert context.job.retries_left == 0


@pytest.mark.parametrize("over_budget", [False, True])
async def test_digest_marker_collision_uses_raw_input_with_step_two_guard(context, monkeypatch, over_budget):
    source = "متن  ساختگی [مرجع نمونه]\n" + (LONG_SYNTHETIC if over_budget else "C++")
    analyze = AsyncMock(return_value=response())

    class Client:
        def __init__(self, *args, **kwargs):
            self.analyze = analyze

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(settings, "RESUME_MODEL_INPUT", "digest_l2")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(pipeline, "InferenceClient", Client)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(pipeline, "parse_resume_text", lambda *_args, **_kwargs: SimpleNamespace(model_dump=dict))

    async def run():
        await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")

    if over_budget:
        with pytest.raises(worker.ResumeProcessingError, match="^input_exceeds_model_budget$"):
            await run()
        analyze.assert_not_called()
    else:
        await run()
        analyze.assert_awaited_once()
        assert analyze.call_args.args[0].resume_text == source
    metrics = context.resume.processing_state["metrics"]
    assert metrics["digest_marker_collision"] == 1
    assert metrics["effective_input_mode"] == "raw"
    assert "digest_level" not in metrics


async def test_shared_cap_rejects_when_essential_content_alone_exceeds_prompt_budget(context, monkeypatch):
    text = "Audience: " + LONG_SYNTHETIC.replace("\n", " ")
    monkeypatch.setattr(settings, "RESUME_MODEL_INPUT", "digest_l2")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: text)
    monkeypatch.setattr(pipeline, "parse_resume_text", lambda *_args, **_kwargs: SimpleNamespace(model_dump=dict))
    model = AsyncMock()
    monkeypatch.setattr(pipeline, "InferenceClient", model)
    with pytest.raises(worker.ResumeProcessingError, match="^input_exceeds_model_budget$"):
        await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")
    model.assert_not_called()
    metrics = context.resume.processing_state["metrics"]
    assert metrics["digest_level"] == 0 and metrics["digest_compaction_skipped_no_evidence"] == 1
    assert metrics["omitted_chars"] == 0 and metrics["over_by"] > 0 and context.resume.raw_text == text


@pytest.mark.parametrize("is_assigned", [False, True], ids=["unassigned-span", "record-description"])
async def test_l2_omission_hides_unsupported_model_results(context, monkeypatch, is_assigned):
    source = "synthetic resume"
    context.application.score_ai = 60
    context.resume.processing_state = {"file_sha256": hashlib.sha256(b"synthetic").hexdigest()}
    client = AsyncMock()
    client.__aenter__.return_value.analyze = AsyncMock(return_value=response())

    class Builder:
        coverage = {"assigned": 5, "unassigned": 11, "coverage_pct": 31.25, "ambiguous_attribution": 0}

        def __init__(self, *_args, **_kwargs):
            pass

        def build(self, level, measure, *, cap):
            return SimpleNamespace(
                level=level,
                text="synthetic",
                budget=measure("synthetic"),
                coverage=self.coverage,
                cap_used=5,
                omitted_by_record={"activity-1": 7} if is_assigned else {},
                unassigned_omitted=0 if is_assigned else 7,
            )

    monkeypatch.setattr(settings, "RESUME_MODEL_INPUT", "digest_l2")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(pipeline, "ResumeDigestBuilder", Builder)
    monkeypatch.setattr(pipeline, "InferenceClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(pipeline, "parse_resume_text", lambda *_args, **_kwargs: SimpleNamespace(model_dump=dict))
    await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")
    assert context.resume.processing_state["metrics"]["model_score_suppressed"] == 1
    assert context.resume.agent_analysis["matching"]["score"] is None
    assert context.resume.agent_analysis["matching"]["matched_required_skills"] == []
    assert context.application.score_ai is None
    assert all(flag["source"] != "model_prediction" for flag in context.resume.agent_analysis["flags"])
    assert any(flag["code"] == "MODEL_SCORE_EVIDENCE_INCOMPLETE" for flag in context.resume.agent_analysis["flags"])


@pytest.mark.parametrize(
    "model_answer",
    [[True, True], [True, False]],
    ids=["agrees", "rejects-one-source"],
)
async def test_fast_evidence_path_keeps_complete_profile(context, monkeypatch, model_answer):
    source = "EXPERIENCE\nBackend Developer\nSynthetic Systems\n2021 to 2023\nSKILLS\nPython\nDocker"
    client = AsyncMock()
    connection = client.__aenter__.return_value
    connection.verify_evidence = AsyncMock(
        return_value=VerifyEvidenceResponse(
            matches=model_answer,
            input_tokens=100,
            output_tokens=8,
        )
    )
    monkeypatch.setattr(settings, "MODEL_EVIDENCE_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(pipeline, "InferenceClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        "app.tasks.resume_processing._load_job_context",
        AsyncMock(return_value={"title": "Test", "skills_required": ["Python", "Docker"]}),
    )
    await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")
    connection.analyze.assert_not_awaited()
    connection.verify_evidence.assert_awaited_once()
    assert context.resume.raw_text == source
    assert len(context.resume.parsed_data["structured"]["activities"]) == 1
    assert context.resume.processing_state["metrics"]["evidence_checked"] == 2
    assert context.application.score_ai is None
    expected = "MODEL_EVIDENCE_VERIFIED" if all(model_answer) else "MODEL_MATCHING_EVIDENCE_CONFLICT"
    assert expected in {flag["code"] for flag in context.resume.agent_analysis["flags"]}


@pytest.mark.parametrize("long_input", [True, False], ids=["over-budget", "within-budget"])
async def test_mixed_requirements_keep_all_source_evidence(context, monkeypatch, long_input):
    structured_text = "EXPERIENCE\nBackend Developer\nSynthetic Systems\n2021 to 2023\nSKILLS\nPython"
    source = f"{LONG_SYNTHETIC}\n{structured_text}" if long_input else structured_text
    client = AsyncMock()
    connection = client.__aenter__.return_value
    connection.verify_evidence.return_value = VerifyEvidenceResponse(matches=[True], input_tokens=60, output_tokens=4)
    connection.analyze.return_value = response()
    monkeypatch.setattr(settings, "MODEL_EVIDENCE_CHECK_ENABLED", True)
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_CONTEXT_LIMIT", 2048)
    monkeypatch.setattr(settings, "MODEL_INFERENCE_OUTPUT_LIMIT", 640)
    monkeypatch.setattr(settings, "RESUME_MODEL_INPUT", "raw")
    monkeypatch.setattr(pipeline, "InferenceClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        "app.tasks.resume_processing._load_job_context",
        AsyncMock(
            return_value={
                "title": "آگهی آزمایشی",
                "skills_required": ["Python", "Docker"],
                "required_seniority": "Senior",
                "location": "Oslo",
            }
        ),
    )

    await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")

    assert context.resume.raw_text == source
    assert len(context.resume.parsed_data["structured"]["activities"]) == 1
    rows = context.resume.parsed_data["_evidence_analysis"]["requirements"]
    assert [row["status"] for row in rows] == ["met", "unknown", "unknown", "unknown"]
    assert context.resume.processing_state["status"] == "succeeded"
    if long_input:
        connection.analyze.assert_not_awaited()
        connection.verify_evidence.assert_awaited_once()
        assert [check.skill for check in connection.verify_evidence.call_args.args[0].checks] == ["Python"]
        metrics = context.resume.processing_state["metrics"]
        assert metrics["over_by"] > 0 and metrics["evidence_budget_limited"] == 1
        assert metrics["evidence_checked"] == metrics["evidence_agreements"] == 1
        assert context.application.score_ai is None
        assert "MODEL_EVIDENCE_BUDGET_LIMITED" in {flag["code"] for flag in context.resume.agent_analysis["flags"]}
    else:
        connection.verify_evidence.assert_not_awaited()
        connection.analyze.assert_awaited_once()
        assert connection.analyze.call_args.args[0].resume_text == source


@pytest.mark.parametrize(
    ("declared", "predicted", "conflict"),
    [
        (["Python", "Docker"], ["Python"], True),
        (["Python", "Docker"], ["پایتون", "Docker"], False),
        (["Python or Docker"], ["Python"], False),
    ],
    ids=["missing-source-match", "recognized-alias", "alternative-requirement"],
)
async def test_complete_input_model_matching_is_checked_against_source(
    context, monkeypatch, declared, predicted, conflict
):
    reply = response()
    reply.analysis.matched_skills = predicted
    client = AsyncMock()
    client.__aenter__.return_value.analyze = AsyncMock(return_value=reply)
    monkeypatch.setattr(settings, "RESUME_MODEL_INPUT", "digest_l0")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_TOKENIZER_FILE", "")
    monkeypatch.setattr(pipeline, "InferenceClient", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *_args, **_kwargs: "مهارت‌ها\nPython\nDocker")
    monkeypatch.setattr(
        "app.tasks.resume_processing._load_job_context",
        AsyncMock(return_value={"title": "Test", "skills_required": declared}),
    )

    await worker.run_model_job(APP_ID, "synthetic.pdf", context.session, lambda _: b"synthetic")

    metrics = context.resume.processing_state["metrics"]
    assert metrics["omitted_chars"] == 0
    assert context.resume.parsed_data["_evidence_analysis"]["coverage"]["met"] == len(declared)
    flags = {flag["code"] for flag in context.resume.agent_analysis["flags"]}
    if conflict:
        assert "MODEL_MATCHING_EVIDENCE_CONFLICT" in flags
        assert "MODEL_SCORE_EVIDENCE_INCOMPLETE" not in flags
        assert metrics["model_matching_conflict"] == metrics["model_score_suppressed"] == 1
        assert context.application.score_ai is None
        assert context.resume.agent_analysis["matching"]["matched_required_skills"] == []
    else:
        assert "MODEL_MATCHING_EVIDENCE_CONFLICT" not in flags
        assert context.application.score_ai == 70


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
            {"_extraction": {"version": worker.EXTRACTION_VERSION, "file_sha256": hashlib.sha256(b"test").hexdigest()}},
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
    layout = {"version": worker.EXTRACTION_VERSION, "file_sha256": digest}
    context.resume.raw_text = "synthetic"
    context.resume.parsed_data = {"_extraction": layout, "old": True}
    context.resume.processing_state = {
        "status": "succeeded",
        "file_sha256": digest,
        "extraction_version": worker.EXTRACTION_VERSION,
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
    assert context.resume.processing_state["parser_version"] == worker.PARSER_VERSION


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
            {"_extraction": {"version": worker.EXTRACTION_VERSION, "file_sha256": hashlib.sha256(b"test").hexdigest()}},
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
