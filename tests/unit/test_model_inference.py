"""آزمون مرز شبکه، مهلت، لغو، فشار و جداسازی تصمیم منابع انسانی."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.model_inference.client import InferenceClient, InferenceError
from app.model_inference.contract import (
    INSTRUCTION,
    Analysis,
    AnalyzeRequest,
    AnalyzeResponse,
    GeneratedAnalysis,
    JobContext,
    chat_prompt,
)
from app.model_inference.pipeline import map_analysis
from inference.service import Engine, create_app


def prediction():
    return {
        "score": 70,
        "verdict": "مناسب",
        "matched_skills": ["Python"],
        "missing_skills": [],
        "experience": {"total_years": 3.0, "positions": [], "overlaps": 0, "invalid_periods": 0},
        "soft_skills": [],
        "flags": [],
        "hr_outcome": None,
        "rationale": "نیاز به بررسی انسانی",
    }


def response():
    return AnalyzeResponse(analysis=Analysis(**prediction()), input_tokens=100, output_tokens=200, model="ats-q4")


def request():
    return AnalyzeRequest(resume_text="Python developer", job=JobContext(title="Developer"))


def test_prompt_matches_training():
    from app.datasets.finetune.records import INSTRUCTION as TRAIN_INSTRUCTION

    assert INSTRUCTION == TRAIN_INSTRUCTION
    assert chat_prompt(request()).endswith("<|im_start|>assistant\n")


def test_grammar_fingerprint_precedes_mutating_converter(tmp_path, monkeypatch):
    import hashlib
    from inference import prepare_grammar

    converter = tmp_path / "converter.py"
    converter.write_text(
        "class SchemaConverter:\n"
        " def __init__(self, **kwargs): pass\n"
        " def resolve_refs(self, schema, url):\n"
        "  schema['changed_by_resolver'] = True\n"
        "  return schema\n"
        " def visit(self, schema, name): pass\n"
        " def format_grammar(self): return 'root ::= \"x\"'\n",
        encoding="utf-8",
    )
    output = tmp_path / "grammar.json"
    monkeypatch.setattr(prepare_grammar, "CONVERTER_SHA256", hashlib.sha256(converter.read_bytes()).hexdigest())
    monkeypatch.setattr("sys.argv", ["prepare", "--converter", str(converter), "--output", str(output)])
    expected = hashlib.sha256(
        json.dumps(GeneratedAnalysis.model_json_schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prepare_grammar.main()
    assert json.loads(output.read_text(encoding="utf-8"))["schema_sha256"] == expected


@pytest.mark.parametrize("valid_hash", [True, False])
async def test_hybrid_artifact_cannot_weaken_response_validation(tmp_path, monkeypatch, valid_hash):
    import hashlib

    monkeypatch.setenv("INFERENCE_ENGINE", "llama_cpp")
    schema_hash = hashlib.sha256(
        json.dumps(GeneratedAnalysis.model_json_schema(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    artifact = tmp_path / "grammar.json"
    artifact.write_text(
        json.dumps({"grammar": 'root ::= "x"', "schema_sha256": schema_hash if valid_hash else "stale"})
    )
    monkeypatch.setenv("INFERENCE_GRAMMAR_FILE", str(artifact))

    async def handler(req):
        body = json.loads(req.content)
        assert body["grammar"] == 'root ::= "x"'
        assert "json_schema" not in body
        assert body["n_predict"] == 640
        incomplete = prediction()
        del incomplete["rationale"]
        return httpx.Response(200, json={"content": json.dumps(incomplete), "stop_type": "eos", "tokens_predicted": 10})

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        if valid_hash:
            engine = Engine(http=http, tokenizer=FakeTokenizer())
            with pytest.raises(InferenceError, match="invalid_engine_response"):
                await engine.analyze(request())
        else:
            with pytest.raises(ValueError, match="grammar"):
                Engine(http=http, tokenizer=FakeTokenizer())


async def test_zero_waiting_rejects_overload_and_releases_capacity(monkeypatch):
    monkeypatch.setenv("INFERENCE_WAITING", "0")
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(req):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"done": True, "response": json.dumps(prediction()), "eval_count": 20})

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        first = asyncio.create_task(engine.analyze(request()))
        await entered.wait()
        try:
            with pytest.raises(InferenceError) as error:
                await engine.analyze(request())
            assert error.value.status_code == 429
        finally:
            release.set()
            await first
        assert engine.capacity.pending == 0


async def test_cpp_warms_each_slot_with_complete_synthetic_response(monkeypatch):
    monkeypatch.setenv("INFERENCE_ENGINE", "llama_cpp")
    monkeypatch.setenv("INFERENCE_CPP_WARMUP", "1")
    monkeypatch.setenv("INFERENCE_PARALLEL", "2")
    requests = []

    async def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        body = json.loads(req.content)
        assert body["n_predict"] == 640
        assert "این متن ساختگی" in body["prompt"]
        requests.append(body)
        return httpx.Response(200, json={"content": json.dumps(prediction()), "stop_type": "eos"})

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        await engine.warm()
        assert engine.ready and len(requests) == 2


@pytest.mark.parametrize("field,value", [("score", True), ("score", 101), ("score", "70"), ("unknown", 1)])
def test_reject_bad_contract(field, value):
    payload = prediction()
    payload[field] = value
    with pytest.raises(ValidationError):
        Analysis.model_validate(payload)


def test_hr_prediction_never_trusted():
    payload = prediction()
    payload["hr_outcome"] = {"status": "Offer", "interview_score": None}
    GeneratedAnalysis.model_validate(payload)
    with pytest.raises(ValidationError):
        Analysis.model_validate(payload)
    result = map_analysis(response(), "Python", {}, 20)
    assert result.status == "partial"
    assert result.experience.status == "failed"
    assert "hr_outcome" not in json.dumps(result.model_dump())
    assert result.matching.score == 70


async def test_async_pool_concurrency_overload_and_loop_responsive():
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def handler(req):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return httpx.Response(200, json=response().model_dump())

    async with InferenceClient(
        "http://inference", lambda: "test", active=1, waiting=1, transport=httpx.MockTransport(handler)
    ) as client:
        first = asyncio.create_task(client.analyze(request()))
        await started.wait()
        second = asyncio.create_task(client.analyze(request()))
        await asyncio.sleep(0.01)
        assert calls == 1
        with pytest.raises(InferenceError) as error:
            await client.analyze(request())
        assert error.value.status_code == 429
        # timer هنگام انتظار پاسخ جلو می‌رود؛ هیچ فراخوانی همگام مسدودکننده‌ای وجود ندارد.
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.1)
        release.set()
        await asyncio.gather(first, second)
        assert calls == 2
        assert client.capacity.pending == 0


async def test_cancel_releases_slot_and_connection():
    entered = asyncio.Event()

    async def handler(req):
        entered.set()
        await asyncio.sleep(20)

    async with InferenceClient("http://inference", lambda: "test", transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(client.analyze(request()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.capacity.pending == 0


@pytest.mark.parametrize("mode,code", [("slow", 504), ("invalid", 502), ("down", 503), ("huge", 502)])
async def test_failures_sanitized_and_bounded(mode, code):
    async def handler(req):
        if mode == "slow":
            await asyncio.sleep(1)
        if mode == "down":
            raise httpx.ConnectError("sensitive text")
        return httpx.Response(200, content=b"x" * (70000 if mode == "huge" else 1))

    async with InferenceClient(
        "http://inference", lambda: "test", timeout=0.05, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(InferenceError) as error:
            await client.analyze(request())
        assert error.value.status_code == code
        assert "sensitive" not in str(error.value)
        assert client.capacity.pending == 0


class FakeTokenizer:
    def encode(self, text, **kwargs):
        return type("Encoded", (), {"ids": list(range(10))})()


async def test_readiness_warms_generation_with_synthetic_input():
    async def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 1
        assert body["prompt"] == "ATS synthetic warmup. " * 128
        assert body["format"]["required"]
        return httpx.Response(200, json={"done": True})

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        assert not engine.ready
        await engine.warm()
        assert engine.ready
        assert engine.output == 640


async def test_engine_schema_hr_sanitizing_and_output_length():
    payload = prediction()
    payload["hr_outcome"] = {"status": "Offer", "interview_score": None}
    reason = "stop"

    async def handler(req):
        data = json.loads(req.content)
        assert data["raw"] is True
        assert "score" in data["format"]["required"]
        return httpx.Response(
            200, json={"done": True, "done_reason": reason, "response": json.dumps(payload), "eval_count": 200}
        )

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        output = await engine.analyze(request())
        assert output.analysis.hr_outcome is None
        reason = "length"
        with pytest.raises(InferenceError, match="incomplete_generation"):
            await engine.analyze(request())
        engine.context = 20
        with pytest.raises(InferenceError) as error:
            await engine.analyze(request())
        assert error.value.status_code == 422


@pytest.mark.parametrize("stop_type,accepted", [("eos", True), ("word", True), ("limit", False), ("none", False)])
async def test_llama_cpp_rejects_unfinished_generation(monkeypatch, stop_type, accepted):
    monkeypatch.setenv("INFERENCE_ENGINE", "llama_cpp")

    async def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/completion"
        assert body["n_predict"] == 640
        assert body["cache_prompt"] is False
        return httpx.Response(
            200,
            json={"content": json.dumps(prediction()), "tokens_predicted": 200, "stop_type": stop_type},
        )

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        if accepted:
            assert (await engine.analyze(request())).analysis.score == 70
        else:
            with pytest.raises(InferenceError, match="incomplete_generation"):
                await engine.analyze(request())


@pytest.mark.parametrize("reason,accepted", [("stop", True), ("length", False), (None, False)])
async def test_vllm_preserves_contract_and_rejects_unfinished_output(monkeypatch, reason, accepted):
    monkeypatch.setenv("INFERENCE_ENGINE", "vllm")

    async def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/v1/completions"
        assert body["max_tokens"] == 640
        assert body["guided_json"] == GeneratedAnalysis.model_json_schema()
        assert body["prompt"] == chat_prompt(request())
        return httpx.Response(
            200,
            json={
                "choices": [{"text": json.dumps(prediction()), "finish_reason": reason}],
                "usage": {"completion_tokens": 200},
            },
        )

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        if accepted:
            result = await engine.analyze(request())
            assert result.analysis.score == 70
            assert result.output_tokens == 200
            assert result.analysis.hr_outcome is None
        else:
            with pytest.raises(InferenceError, match="incomplete_generation"):
                await engine.analyze(request())


@pytest.mark.parametrize("startup_status", [200, 503])
async def test_vllm_ready_requires_schema_warmup(monkeypatch, startup_status):
    monkeypatch.setenv("INFERENCE_ENGINE", "vllm")

    async def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200)
        body = json.loads(req.content)
        assert req.url.path == "/v1/completions"
        assert body["max_tokens"] == 1
        assert body["guided_json"] == GeneratedAnalysis.model_json_schema()
        return httpx.Response(startup_status)

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        if startup_status == 200:
            await engine.warm()
            assert engine.ready
        else:
            with pytest.raises(httpx.HTTPStatusError):
                await engine.warm()
            assert not engine.ready


async def test_service_rejects_unauthorized_and_does_not_echo_input():
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://service") as http:
        result = await http.post("/v1/analyze", json=request().model_dump())
        assert result.status_code == 401
        result = await http.post("/v1/analyze", content=b"x" * 140000)
        assert result.status_code == 413
        assert "Python developer" not in result.text
        assert (await http.get("/health")).status_code == 200


async def test_authenticated_route_stays_responsive_and_sanitizes_validation(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.core import service_auth

    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    monkeypatch.setattr(service_auth, "_private_key", lambda: private)
    monkeypatch.setattr(service_auth, "_public_keys", lambda: {"worker": public})
    token = service_auth.issue_service_token(audience="ats-inference", issuer="worker")
    headers = {"X-Internal-Auth": token}
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowEngine:
        async def analyze(self, body):
            entered.set()
            await release.wait()
            return response()

    app = create_app()
    app.state.engine = SlowEngine()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://service") as http:
        task = asyncio.create_task(http.post("/v1/analyze", json=request().model_dump(), headers=headers))
        await asyncio.wait_for(entered.wait(), 1)
        assert (await asyncio.wait_for(http.get("/health"), 0.2)).status_code == 200
        release.set()
        assert (await task).status_code == 200
        bad = await http.post("/v1/analyze", json={"resume_text": "private-secret"}, headers=headers)
        assert bad.status_code == 422
        assert "private-secret" not in bad.text


async def test_asgi_disconnect_cancels_engine_and_drains_capacity():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def handler(req):
        entered.set()
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    async with httpx.AsyncClient(base_url="http://engine", transport=httpx.MockTransport(handler)) as http:
        engine = Engine(http=http, tokenizer=FakeTokenizer())
        app = create_app()
        app.state.engine = engine
        route = next(route for route in app.routes if route.path == "/v1/analyze")
        app.dependency_overrides[route.dependant.dependencies[0].call] = lambda: object()
        messages = asyncio.Queue()
        messages.put_nowait({"type": "http.request", "body": request().model_dump_json().encode(), "more_body": False})
        sent = []

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/v1/analyze",
            "raw_path": b"/v1/analyze",
            "query_string": b"",
            "scheme": "http",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "server": ("test", 80),
            "client": ("test", 1000),
        }
        task = asyncio.create_task(app(scope, messages.get, send))
        await asyncio.wait_for(entered.wait(), 1)
        assert engine.capacity.pending == 1
        messages.put_nowait({"type": "http.disconnect"})
        await asyncio.wait_for(task, 1)
        assert cancelled.is_set()
        assert engine.capacity.pending == 0
        assert sent[0]["status"] == 499


async def test_model_pipeline_waits_outside_database_and_preserves_hr(monkeypatch):
    from app.core.config import settings
    from app.models import Application, Resume
    from app.tasks import resume_processing as processing

    application = SimpleNamespace(status="Applied", score_ai=None)
    resume = SimpleNamespace(id="resume-id", candidate_id="candidate-id")
    active = 0

    class Session:
        async def __aenter__(self):
            nonlocal active
            active += 1
            return self

        async def __aexit__(self, *args):
            nonlocal active
            active -= 1

        async def execute(self, query):
            return SimpleNamespace(scalar_one_or_none=lambda: resume)

        async def get(self, model, identifier):
            return resume if model is Resume else application if model is Application else None

        async def commit(self):
            pass

    async def model_pipeline(*args):
        assert active == 0
        await asyncio.sleep(0.01)
        return SimpleNamespace(raw_text="Python", parsed_data={}, analysis=map_analysis(response(), "Python", {}, 20))

    monkeypatch.setattr(settings, "RESUME_PIPELINE", "model")
    monkeypatch.setattr(processing, "_load_job_context", AsyncMock(return_value={"title": "Developer"}))
    monkeypatch.setattr(processing, "_download_file", lambda url: b"test")
    monkeypatch.setattr("app.model_inference.pipeline.run_model_pipeline", model_pipeline)
    await processing._process_resume_async("00000000-0000-0000-0000-000000000001", "local.pdf", Session)
    assert application.status == "Applied"
    assert application.score_ai == 70
    assert resume.agent_analysis["schema_version"] == "agents-v1"
    assert active == 0


async def test_nullable_database_skills_map_to_empty_request(monkeypatch):
    from app.model_inference import pipeline

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def analyze(self, body):
            assert body.job.skills_required == []
            assert body.job.title == "Developer"
            return response()

    monkeypatch.setattr(pipeline, "InferenceClient", FakeClient)
    monkeypatch.setattr(pipeline, "extract_raw_text", lambda *args, **kwargs: "Python")
    monkeypatch.setattr(pipeline, "parse_resume_text", lambda text: SimpleNamespace(model_dump=lambda: {}))
    result = await pipeline.run_model_pipeline(b"test", "test.pdf", {"title": "Developer", "skills_required": None})
    assert result.analysis.matching.score == 70
