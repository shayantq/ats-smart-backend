"""درگاه داخلی Ollama؛ متن و توکن احراز هویت هرگز وارد لاگ نمی‌شوند."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from contextlib import aclosing, asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from tokenizers import Tokenizer
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.service_auth import require_service_token
from app.model_inference.client import Capacity, InferenceError, SAFE_TIMINGS
from app.model_inference.contract import (
    Analysis,
    AnalyzeRequest,
    AnalyzeResponse,
    GeneratedAnalysis,
    JobContext,
    EVIDENCE_INPUT_TOKENS,
    EVIDENCE_OUTPUT_TOKENS,
    VerifyEvidenceRequest,
    VerifyEvidenceResponse,
    chat_prompt,
    evidence_prompt,
)


class BoundedBodyMiddleware:
    """ASGI مستقیم؛ کانال disconnect برای لغو درخواست دست‌نخورده می‌ماند."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope.get("headers", [])).get(b"content-length", b"0")
        if length.isdigit() and int(length) > 131072:
            response = JSONResponse(
                status_code=413, content={"detail": "request_too_large"}, headers={"Connection": "close"}
            )
            return await response(scope, receive, send)
        chunks, size = [], 0
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > 131072:
                        response = JSONResponse(
                            status_code=413, content={"detail": "request_too_large"}, headers={"Connection": "close"}
                        )
                        return await response(scope, receive, send)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            response = JSONResponse(
                status_code=408, content={"detail": "request_body_timeout"}, headers={"Connection": "close"}
            )
            return await response(scope, receive, send)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class Engine:
    def __init__(self, *, http=None, tokenizer=None):
        self.kind = os.getenv("INFERENCE_ENGINE", "ollama")
        if self.kind not in ("ollama", "llama_cpp", "vllm"):
            raise ValueError("موتور ناشناخته است")
        self.model = os.getenv("INFERENCE_MODEL", "ats-q4")
        self.context = int(os.getenv("INFERENCE_CONTEXT", "2048"))
        self.output = int(os.getenv("INFERENCE_MAX_OUTPUT", "640"))
        self.deadline = float(os.getenv("INFERENCE_TIMEOUT", "60"))
        self.startup_timeout = float(os.getenv("INFERENCE_STARTUP_TIMEOUT", "180"))
        self.parallel = int(os.getenv("INFERENCE_PARALLEL", "1"))
        self.capacity = Capacity(self.parallel, int(os.getenv("INFERENCE_WAITING", "4")))
        self.tokenizer_sha256 = None
        if tokenizer is None:
            data = Path(os.environ["INFERENCE_TOKENIZER"]).read_bytes()
            self.tokenizer_sha256 = hashlib.sha256(data).hexdigest()
            tokenizer = Tokenizer.from_buffer(data)
        self.tokenizer = tokenizer
        self.http = http or httpx.AsyncClient(
            base_url=os.getenv("OLLAMA_URL", "http://ats-engine:11434"),
            timeout=httpx.Timeout(self.deadline, connect=3),
            limits=httpx.Limits(max_connections=6, max_keepalive_connections=6),
            trust_env=False,
        )
        self.ready = False
        self.grammar = None
        if os.getenv("INFERENCE_GRAMMAR_FILE"):
            artifact = json.loads(Path(os.environ["INFERENCE_GRAMMAR_FILE"]).read_text(encoding="utf-8"))
            schema = json.dumps(GeneratedAnalysis.model_json_schema(), sort_keys=True, separators=(",", ":"))
            if self.kind != "llama_cpp" or artifact.get("schema_sha256") != hashlib.sha256(schema.encode()).hexdigest():
                raise ValueError("grammar با قرارداد فعلی یا موتور سازگار نیست")
            self.grammar = artifact["grammar"]

    async def warm(self):
        if self.kind in ("llama_cpp", "vllm"):
            async with asyncio.timeout(self.startup_timeout):
                while True:
                    try:
                        response = await self.http.get("/health")
                        response.raise_for_status()
                        break
                    except httpx.HTTPError:
                        await asyncio.sleep(1)
            if self.kind == "vllm":
                # ساخت grammar و گرم‌کردن startup؛ درخواست واقعی همیشه سقف کامل خود را دارد.
                response = await self.http.post(
                    "/v1/completions",
                    json={
                        "model": self.model,
                        "prompt": "ATS synthetic warmup.",
                        "stream": False,
                        "max_tokens": 1,
                        "temperature": 0,
                        "guided_json": GeneratedAnalysis.model_json_schema(),
                        "guided_decoding_backend": "xgrammar",
                    },
                    timeout=httpx.Timeout(self.startup_timeout, connect=5),
                )
                response.raise_for_status()
            elif os.getenv("INFERENCE_CPP_WARMUP", "0") == "1":

                async def warm_slot(index):
                    # پوشش bucket بلندِ attention پیش از readiness؛ هیچ نمونهٔ واقعی در warmup نیست.
                    def synthetic_prompt(repeats):
                        return chat_prompt(
                            AnalyzeRequest(
                                resume_text="این متن ساختگی فقط برای آماده‌سازی موتور است. " * repeats,
                                job=JobContext(title="آزمون آماده‌سازی"),
                            )
                        )

                    budget = min(1152 + 32 * index, self.context - self.output - 16)
                    low, high = 1, 200
                    while low < high:
                        middle = (low + high + 1) // 2
                        count = len(self.tokenizer.encode(synthetic_prompt(middle), add_special_tokens=False).ids)
                        if count <= budget:
                            low = middle
                        else:
                            high = middle - 1
                    prompt = synthetic_prompt(low)
                    response = await self.http.post(
                        "/completion",
                        json={
                            "prompt": prompt,
                            "cache_prompt": False,
                            "stream": False,
                            "n_predict": self.output,
                            "temperature": 0,
                            "seed": 2026,
                            "top_k": 0,
                            "top_p": 1.0,
                            "repeat_penalty": 1.0,
                            "min_p": 0.0,
                            "samplers": ["temperature"],
                            **(
                                {"grammar": self.grammar}
                                if self.grammar
                                else {"json_schema": GeneratedAnalysis.model_json_schema()}
                            ),
                        },
                        timeout=httpx.Timeout(self.startup_timeout, connect=5),
                    )
                    response.raise_for_status()
                    result = response.json()
                    if result.get("stop_type") not in ("eos", "word") or result.get("truncated", False):
                        raise ValueError("آماده‌سازی کامل موتور پایان نیافت")
                    GeneratedAnalysis.model_validate_json(result["content"])

                await asyncio.gather(*(warm_slot(index) for index in range(self.parallel)))
            self.ready = True
            return
        response = await self.http.post(
            "/api/generate",
            json={
                "model": self.model,
                # فقط گرم‌کردن داخلی با متن ساختگی؛ سقف پاسخ درخواست کاربر همچنان ۶۴۰ است.
                "prompt": "ATS synthetic warmup. " * 128,
                "raw": True,
                "stream": False,
                "format": GeneratedAnalysis.model_json_schema(),
                "keep_alive": -1,
                "options": {"num_ctx": self.context, "num_predict": 1, "temperature": 0},
            },
            timeout=httpx.Timeout(self.startup_timeout, connect=5),
        )
        response.raise_for_status()
        self.ready = True

    async def engine_json(self, endpoint, payload):
        async with self.http.stream("POST", endpoint, json=payload) as response:
            response.raise_for_status()
            body = bytearray()
            async with aclosing(response.aiter_bytes()) as stream:
                async for chunk in stream:
                    body.extend(chunk)
                    if len(body) > 131072:
                        raise InferenceError("engine_response_too_large", 502)
        return json.loads(body)

    async def verify_evidence(self, body: VerifyEvidenceRequest):
        if self.kind != "llama_cpp":
            raise InferenceError("evidence_verification_unavailable", 503)
        prompt = evidence_prompt(body)
        tokens = len(self.tokenizer.encode(prompt, add_special_tokens=False).ids)
        if tokens > EVIDENCE_INPUT_TOKENS or tokens + EVIDENCE_OUTPUT_TOKENS > self.context:
            raise InferenceError("context_limit_exceeded", 422)
        values = ' ws "," ws '.join(["verdict"] * len(body.checks))
        grammar = f'root ::= "[" ws {values} ws "]"\nverdict ::= "true" | "false"\nws ::= [ \\t]?'
        try:
            async with asyncio.timeout(min(self.deadline, 35)), self.capacity.slot():
                started = time.perf_counter()
                data = await self.engine_json(
                    "/completion",
                    dict(
                        prompt=prompt,
                        grammar=grammar,
                        n_predict=EVIDENCE_OUTPUT_TOKENS,
                        temperature=0,
                        seed=2026,
                        cache_prompt=False,
                        stream=False,
                    ),
                )
                if data.get("stop_type") not in {"eos", "word"} or data.get("truncated"):
                    raise InferenceError("incomplete_generation", 502)
                result = VerifyEvidenceResponse(
                    input_tokens=tokens, output_tokens=data["tokens_predicted"], matches=json.loads(data["content"])
                )
                if len(result.matches) != len(body.checks):
                    raise InferenceError("invalid_engine_response", 502)
                result._timings_ms["engine_request_ms"] = (time.perf_counter() - started) * 1000
                return result
        except (TimeoutError, httpx.TimeoutException):
            raise InferenceError("engine_deadline_exceeded", 504) from None
        except httpx.HTTPError:
            raise InferenceError("engine_unavailable", 503) from None
        except (ValueError, KeyError, TypeError, ValidationError):
            raise InferenceError("invalid_engine_response", 502) from None

    async def analyze(self, request: AnalyzeRequest):
        started = time.perf_counter()
        prompt = chat_prompt(request)
        tokens = len(self.tokenizer.encode(prompt, add_special_tokens=False).ids)
        timings = {"prompt_tokenization_ms": (time.perf_counter() - started) * 1000}
        if tokens + self.output > self.context:
            error = InferenceError("context_limit_exceeded", 422)
            error.metrics = {"input_tokens": tokens, "context_limit": self.context, "output_limit": self.output}
            raise error
        try:
            async with asyncio.timeout(self.deadline), self.capacity.slot():
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "raw": True,
                    "stream": False,
                    "format": GeneratedAnalysis.model_json_schema(),
                    "keep_alive": -1,
                    "options": {
                        "num_ctx": self.context,
                        "num_predict": self.output,
                        "temperature": 0,
                        "seed": 2026,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                    },
                }
                if self.kind == "llama_cpp":
                    payload = {
                        "prompt": prompt,
                        "stream": False,
                        "cache_prompt": False,
                        "n_predict": self.output,
                        "temperature": 0,
                        "seed": 2026,
                        "top_k": 0,
                        "top_p": 1.0,
                        "repeat_penalty": 1.0,
                        "min_p": 0.0,
                        "samplers": ["temperature"],
                        "json_schema": GeneratedAnalysis.model_json_schema(),
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                    }
                    if self.grammar:
                        payload.pop("json_schema")
                        payload["grammar"] = self.grammar
                if self.kind == "vllm":
                    payload = {
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "max_tokens": self.output,
                        "temperature": 0,
                        "seed": 2026,
                        "guided_json": GeneratedAnalysis.model_json_schema(),
                        "top_p": 1.0,
                        "top_k": -1,
                        "repetition_penalty": 1.0,
                        "guided_decoding_backend": "xgrammar",
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                    }
                endpoint = {"ollama": "/api/generate", "llama_cpp": "/completion", "vllm": "/v1/completions"}[self.kind]
                started = time.perf_counter()
                data = await self.engine_json(endpoint, payload)
                timings["engine_request_ms"] = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                if self.kind == "llama_cpp":
                    count = data.get("timings", {}).get("prompt_n")
                    if type(count) is int and 0 <= count < 1e9:
                        timings["engine_prompt_tokens"] = count
                    for key in ("prompt_ms", "predicted_ms"):
                        value = data.get("timings", {}).get(key)
                        if isinstance(value, (int, float)) and 0 <= value < 1e9:
                            timings["engine_" + key] = value
                    data = {
                        "done": data.get("stop_type") in ("eos", "word") and not data.get("truncated", False),
                        "done_reason": "length" if data.get("stop_type") == "limit" else "stop",
                        "response": data["content"],
                        "eval_count": data["tokens_predicted"],
                    }
                elif self.kind == "vllm":
                    choice = data["choices"][0]
                    data = {
                        "done": choice["finish_reason"] == "stop",
                        "done_reason": choice["finish_reason"],
                        "response": choice["text"],
                        "eval_count": data["usage"]["completion_tokens"],
                    }
                if not data.get("done") or data.get("done_reason") == "length":
                    raise InferenceError("incomplete_generation", 502)
                generated = GeneratedAnalysis.model_validate_json(data["response"])
                payload = generated.model_dump()
                payload["hr_outcome"] = None
                timings["response_validation_ms"] = (time.perf_counter() - started) * 1000
                result = AnalyzeResponse(
                    analysis=Analysis.model_validate(payload),
                    input_tokens=tokens,
                    output_tokens=data["eval_count"],
                    model=self.model,
                )
                result._timings_ms = timings
                return result
        except (TimeoutError, httpx.TimeoutException):
            raise InferenceError("engine_deadline_exceeded", 504) from None
        except httpx.HTTPError:
            raise InferenceError("engine_unavailable", 503) from None
        except (ValueError, KeyError, IndexError, TypeError, ValidationError):
            raise InferenceError("invalid_engine_response", 502) from None


def create_app(engine=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine or Engine()
        # شکست بارگذاری به معنی آماده نبودن سرویس است؛ مدل ناموجود خودکار دانلود نمی‌شود.
        await app.state.engine.warm()
        try:
            yield
        finally:
            app.state.engine.ready = False
            await app.state.engine.http.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # خطای پیش‌فرض Pydantic ممکن است خود متن ورودی را بازتاب دهد.
        return JSONResponse(status_code=422, content={"detail": "invalid_request"})

    app.add_middleware(BoundedBodyMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "alive"}

    @app.get("/ready")
    async def ready(request: Request):
        current = request.app.state.engine
        try:
            async with asyncio.timeout(2):
                response = await current.http.get("/api/ps" if current.kind == "ollama" else "/health")
                response.raise_for_status()
                loaded = current.kind != "ollama" or any(
                    m["name"].split(":")[0] == current.model for m in response.json()["models"]
                )
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError):
            loaded = False
        if not current.ready or not loaded:
            raise HTTPException(503, "model_not_ready")
        return {"status": "ready", "model": current.model, "inflight": current.capacity.pending}

    @app.get("/v1/limits", response_model=None)
    async def limits(
        request: Request, claims=Depends(require_service_token("backend-api", "worker", audience="ats-inference"))
    ):
        current = request.app.state.engine
        result = dict(
            context_limit=current.context,
            output_limit=current.output,
            tokenizer_sha256=current.tokenizer_sha256,
            parallel=current.parallel,
            deadline_seconds=current.deadline,
        )
        build = os.getenv("APP_VERSION", "")
        if build and len(build) <= 64 and build.isascii() and all(c.isalnum() or c in "_-" for c in build):
            result["build"] = build
        return result

    async def run_request(call, request, response):
        async def disconnected():
            while (await request.receive())["type"] != "http.disconnect":
                pass

        task = asyncio.create_task(call)
        monitor = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait((task, monitor), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                result = await task
                for key in SAFE_TIMINGS:
                    if key in result.timings_ms:
                        response.headers["X-ATS-Time-" + key.replace("_", "-")] = str(result.timings_ms[key])
                if "engine_prompt_tokens" in result.timings_ms:
                    response.headers["X-ATS-Time-Engine-Prompt-Tokens"] = str(result.timings_ms["engine_prompt_tokens"])
                return result
            raise HTTPException(499, "client_disconnected")
        except InferenceError as error:
            headers = {
                "X-ATS-" + key.replace("_", "-"): str(value)
                for key, value in error.metrics.items()
                if key in ("input_tokens", "context_limit", "output_limit")
            }
            raise HTTPException(error.status_code, error.code, headers=headers) from None
        finally:
            task.cancel()
            monitor.cancel()
            await asyncio.gather(task, monitor, return_exceptions=True)

    @app.post("/v1/analyze", response_model=AnalyzeResponse)
    async def analyze(
        body: AnalyzeRequest,
        request: Request,
        response: Response,
        claims=Depends(require_service_token("backend-api", "worker", audience="ats-inference")),
    ):
        return await run_request(request.app.state.engine.analyze(body), request, response)

    @app.post("/v1/verify-evidence", response_model=VerifyEvidenceResponse)
    async def verify_evidence(
        body: VerifyEvidenceRequest,
        request: Request,
        response: Response,
        claims=Depends(require_service_token("backend-api", "worker", audience="ats-inference")),
    ):
        return await run_request(request.app.state.engine.verify_evidence(body), request, response)

    return app


app = create_app()
