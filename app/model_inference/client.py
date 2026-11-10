"""کلاینت async با صف محدود، مهلت سراسری و اتصال‌های قابل استفادهٔ مجدد."""

import asyncio
from contextlib import aclosing, asynccontextmanager

import httpx
from pydantic import ValidationError

from app.model_inference.contract import AnalyzeRequest, AnalyzeResponse


class InferenceError(Exception):
    def __init__(self, code: str, status_code: int = 503):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class Capacity:
    def __init__(self, active: int, waiting: int):
        if active < 1 or waiting < 0:
            raise ValueError("ظرفیت نامعتبر است")
        self.limit = active + waiting
        self.pending = 0
        self.semaphore = asyncio.Semaphore(active)

    @asynccontextmanager
    async def slot(self):
        # بدون await بین بررسی و افزایش؛ در یک event loop اتمیک است.
        if self.pending >= self.limit:
            raise InferenceError("overloaded", 429)
        self.pending += 1
        try:
            async with self.semaphore:
                yield
        finally:
            self.pending -= 1


class InferenceClient:
    def __init__(self, url, token_factory, *, timeout=60.0, active=2, waiting=4, transport=None):
        if not url or timeout <= 0:
            raise ValueError("نشانی سرویس و مهلت باید تنظیم شوند")
        self.timeout = timeout
        self.token_factory = token_factory
        self.capacity = Capacity(active, waiting)
        self.http = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            limits=httpx.Limits(max_connections=active, max_keepalive_connections=active),
            transport=transport,
            trust_env=False,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        try:
            # زمان صف، امضا، ارسال و اعتبارسنجی همگی داخل مهلت قرار دارند.
            async with asyncio.timeout(self.timeout), self.capacity.slot():
                token = self.token_factory()
                async with self.http.stream(
                    "POST", "/v1/analyze", json=request.model_dump(), headers={"X-Internal-Auth": token}
                ) as response:
                    if response.status_code != 200:
                        code = response.status_code if response.status_code in (429, 503, 504) else 502
                        raise InferenceError("inference_http_error", code)
                    body = bytearray()
                    async with aclosing(response.aiter_bytes()) as stream:
                        async for chunk in stream:
                            body.extend(chunk)
                            if len(body) > 65536:
                                raise InferenceError("response_too_large", 502)
                return AnalyzeResponse.model_validate_json(bytes(body))
        except (TimeoutError, httpx.TimeoutException):
            raise InferenceError("deadline_exceeded", 504) from None
        except httpx.HTTPError:
            raise InferenceError("inference_unavailable", 503) from None
        except ValidationError:
            raise InferenceError("invalid_inference_response", 502) from None
