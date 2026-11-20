import hashlib

import httpx
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel

from app.core.config import Settings, settings
from app.model_inference import limits
from inference.service import Engine, create_app


@pytest.fixture
def response_data():
    return dict(context_limit=4096, output_limit=640, tokenizer_sha256="a" * 64, parallel=1, deadline_seconds=75)


async def test_gateway_limits_requires_auth_and_hashes_the_loaded_file_once(tmp_path, monkeypatch):
    file = tmp_path / "tokenizer.json"
    Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]")).save(str(file))
    expected = hashlib.sha256(file.read_bytes()).hexdigest()
    monkeypatch.setenv("INFERENCE_TOKENIZER", str(file))
    monkeypatch.setenv("APP_VERSION", "test-build")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("engine called"))) as engine_http:
        engine = Engine(http=engine_http)
        file.write_bytes(b"unreadable")
        app = create_app(engine)
        app.state.engine = engine
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/v1/limits")).status_code in (401, 403)
            route = next(route for route in app.routes if route.path == "/v1/limits")
            app.dependency_overrides[route.dependant.dependencies[0].call] = lambda: object()
            payload = (await client.get("/v1/limits")).json()
    assert payload == dict(
        context_limit=engine.context,
        output_limit=engine.output,
        tokenizer_sha256=expected,
        parallel=engine.parallel,
        deadline_seconds=engine.deadline,
        build="test-build",
    )


@pytest.mark.parametrize("case", ["off", "missing", "ok", "invalid_json", "invalid_limits", "timeout", "unreachable"])
async def test_fetch_limits_falls_back_without_retry_or_uses_ttl(monkeypatch, response_data, case):
    client_class = httpx.AsyncClient
    calls = []
    monkeypatch.setattr(limits, "_cached", {})
    monkeypatch.setattr(settings, "MODEL_INFERENCE_LIMITS_SYNC", case != "off")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_URL", "http://fake.invalid")
    monkeypatch.setattr(settings, "MODEL_INFERENCE_LIMITS_TTL_SECONDS", 300)
    monkeypatch.setattr(limits, "issue_service_token", lambda **_: "test-token")

    def handle(request):
        calls.append(request)
        assert request.url.path == "/v1/limits"
        if case == "timeout":
            raise httpx.ReadTimeout("synthetic")
        if case == "unreachable":
            raise httpx.ConnectError("synthetic")
        if case == "missing":
            return httpx.Response(404)
        if case == "invalid_json":
            return httpx.Response(200, content=b"{")
        if case == "invalid_limits":
            return httpx.Response(200, json={**response_data, "output_limit": 9000})
        return httpx.Response(200, json=response_data)

    def mock_client(**kwargs):
        assert kwargs["timeout"] == 2
        return client_class(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(limits.httpx, "AsyncClient", mock_client)
    result = await limits.fetch_limits()
    if case == "ok":
        assert result.model_dump(exclude_none=True) == response_data
        assert (await limits.fetch_limits()) is result
        assert len(calls) == 1
        monkeypatch.setattr(settings, "MODEL_INFERENCE_LIMITS_TTL_SECONDS", 0)
        assert (await limits.fetch_limits()) is not result
        assert len(calls) == 2
    else:
        assert result is None
        assert len(calls) == (0 if case == "off" else 1)


@pytest.mark.parametrize("client,gateway,job,expected", [(60, 60, 300, 1), (61, 60, 120, 1), (61, 60, 121, 0)])
def test_timeout_validation_warns_once_per_configuration(caplog, client, gateway, job, expected):
    limits.validate_timeouts.cache_clear()
    for _ in range(2):
        limits.validate_timeouts(client, gateway, job, 60)
    assert len(caplog.messages) == expected
    defaults = Settings.model_fields
    assert (
        defaults["MODEL_INFERENCE_TIMEOUT_SECONDS"].default
        == defaults["MODEL_INFERENCE_GATEWAY_DEADLINE_SECONDS"].default
        == 60
    )
    assert defaults["RESUME_JOB_TIMEOUT_SECONDS"].default == 300
    assert defaults["RESUME_EXTRACTION_PARSE_ALLOWANCE_SECONDS"].default == 60
