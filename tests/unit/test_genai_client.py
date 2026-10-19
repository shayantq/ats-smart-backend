"""تست واحد کلاینت مستقل از ارائه‌دهنده (app/genai/client.py) با یک سرویس شبیه‌سازی‌شده (httpx.MockTransport)."""

import json

import httpx
import pytest

from app.genai.client import ChatCompletionsClient, GenAINotConfiguredError, GenAIOutputError, GenAIProviderError

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def _client(handler, **overrides) -> ChatCompletionsClient:
    params = {"base_url": "http://llm.test/v1/", "model": "test-model", "api_key": "secret-key"}
    params.update(overrides)
    return ChatCompletionsClient(transport=httpx.MockTransport(handler), **params)


def _ok(content='{"ok": true}', finish_reason="stop"):
    return httpx.Response(
        200,
        json={
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        },
    )


def test_request_follows_chat_completions_protocol_with_json_schema():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return _ok()

    result = _client(handler).complete_json([{"role": "user", "content": "hi"}], schema_name="test", schema=SCHEMA)

    assert captured["url"] == "http://llm.test/v1/chat/completions"
    assert captured["auth"] == "Bearer secret-key"
    body = captured["body"]
    assert body["model"] == "test-model" and body["messages"][0]["content"] == "hi"
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "test", "strict": True, "schema": SCHEMA},
    }
    assert (result.content, result.prompt_tokens, result.completion_tokens) == ('{"ok": true}', 120, 40)


def test_json_object_mode_and_no_auth_header_without_key():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["format"] = json.loads(request.content)["response_format"]
        return _ok()

    _client(handler, api_key="", structured_output="json_object").complete_json([], schema_name="t", schema=SCHEMA)

    assert captured == {"auth": None, "format": {"type": "json_object"}}


@pytest.mark.parametrize("status_code, retryable", [(429, True), (503, True), (500, True), (401, False), (400, False)])
def test_http_errors_are_classified_for_queue_retry(status_code, retryable):
    client = _client(lambda request: httpx.Response(status_code, text="error body"))

    with pytest.raises(GenAIProviderError) as error:
        client.complete_json([], schema_name="t", schema=SCHEMA)

    assert error.value.retryable is retryable and error.value.status_code == status_code
    assert "secret-key" not in str(error.value)


def test_network_failure_is_retryable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(GenAIProviderError) as error:
        _client(handler).complete_json([], schema_name="t", schema=SCHEMA)
    assert error.value.retryable is True


@pytest.mark.parametrize(
    "response", [_ok(finish_reason="length"), _ok(content="  "), httpx.Response(200, json={"x": 1})]
)
def test_truncated_empty_or_malformed_responses_are_output_errors(response):
    with pytest.raises(GenAIOutputError):
        _client(lambda request: response).complete_json([], schema_name="t", schema=SCHEMA)


def test_missing_configuration_disables_the_feature():
    with pytest.raises(GenAINotConfiguredError):
        ChatCompletionsClient(base_url="", model="")
