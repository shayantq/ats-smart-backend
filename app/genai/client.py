"""
کلاینت مستقل از ارائه‌دهنده‌ی مدل زبانی — پروتکل استاندارد Chat Completions روی HTTP.

همین پروتکل را هم سرویس‌های ابری و هم سرورهای مدل داخل کلاستر پشتیبانی می‌کنند؛ انتخاب سرویس فقط با
GENAI_BASE_URL، GENAI_MODEL و GENAI_API_KEY است (app/core/config.py) و هیچ نامی از ارائه‌دهنده یا مدل در
کد نیست.

درخواست:
    POST {GENAI_BASE_URL}/chat/completions
    {"model", "messages", "temperature", "max_tokens",
     "response_format": {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}}
    (GENAI_STRUCTURED_OUTPUT=json_object → {"type": "json_object"} و اعتبارسنجی Schema فقط سمت ما)

خطاها: GenAIProviderError با retryable — قطعی شبکه، Timeout، 408/409/429/5xx قابل تکرارند (صف RQ دوباره
اجرا می‌کند)؛ 4xx دیگر (کلید نامعتبر، مدل ناموجود، درخواست بد) تکرار نمی‌شوند. کلید API هرگز لاگ نمی‌شود.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.core.config import settings

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class GenAIError(Exception):
    """پایه‌ی خطاهای سرویس هوش مصنوعی مولد."""

    retryable = False


class GenAINotConfiguredError(GenAIError):
    """GENAI_BASE_URL یا GENAI_MODEL تنظیم نشده — قابلیت غیرفعال است."""


class GenAIProviderError(GenAIError):
    """خطای ارتباط با سرویس مدل زبانی."""

    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class GenAIOutputError(GenAIError):
    """پاسخ مدل قابل استفاده نیست (قطع‌شده، خالی یا ناسازگار با Schema)."""


@dataclass(frozen=True)
class CompletionResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    finish_reason: str | None


class ChatCompletionsClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 240.0,
        max_output_tokens: int = 4096,
        temperature: float = 0.3,
        structured_output: str = "json_schema",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url or not model:
            raise GenAINotConfiguredError("سرویس هوش مصنوعی مولد پیکربندی نشده است (GENAI_BASE_URL / GENAI_MODEL)")
        if structured_output not in {"json_schema", "json_object"}:
            raise GenAINotConfiguredError(f"GENAI_STRUCTURED_OUTPUT نامعتبر: {structured_output}")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.structured_output = structured_output
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            transport=transport,
        )

    @classmethod
    def from_settings(cls, transport: httpx.BaseTransport | None = None) -> "ChatCompletionsClient":
        return cls(
            base_url=settings.GENAI_BASE_URL,
            model=settings.GENAI_MODEL,
            api_key=settings.GENAI_API_KEY,
            timeout_seconds=settings.GENAI_TIMEOUT_SECONDS,
            max_output_tokens=settings.GENAI_MAX_OUTPUT_TOKENS,
            temperature=settings.GENAI_TEMPERATURE,
            structured_output=settings.GENAI_STRUCTURED_OUTPUT,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ChatCompletionsClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def build_payload(self, messages: list[dict], schema_name: str, schema: dict) -> dict:
        if self.structured_output == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        else:
            response_format = {"type": "json_object"}
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "response_format": response_format,
        }

    def complete_json(self, messages: list[dict], *, schema_name: str, schema: dict) -> CompletionResult:
        """یک فراخوانی Chat Completions با خروجی JSON مقید به Schema."""
        payload = self.build_payload(messages, schema_name, schema)
        started = time.monotonic()
        try:
            response = self._client.post(f"{self.base_url}/chat/completions", json=payload)
        except httpx.TimeoutException as error:
            raise GenAIProviderError(f"پاسخ سرویس مدل زبانی در زمان مقرر نرسید: {error}", retryable=True) from error
        except httpx.TransportError as error:
            raise GenAIProviderError(f"اتصال به سرویس مدل زبانی برقرار نشد: {error}", retryable=True) from error
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            raise GenAIProviderError(
                f"سرویس مدل زبانی خطای {response.status_code} داد: {response.text[:300]}",
                retryable=response.status_code in _RETRYABLE_STATUS,
                status_code=response.status_code,
            )
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise GenAIOutputError(f"ساختار پاسخ سرویس مدل زبانی نامعتبر است: {response.text[:300]}") from error

        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise GenAIOutputError(
                "پاسخ مدل به سقف GENAI_MAX_OUTPUT_TOKENS رسید و ناقص ماند — سقف را افزایش یا تعداد سؤال را کاهش دهید"
            )
        if not content.strip():
            raise GenAIOutputError("پاسخ مدل خالی بود")

        usage = body.get("usage") or {}
        return CompletionResult(
            content=content,
            model=body.get("model") or self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
