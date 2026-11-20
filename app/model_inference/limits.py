import asyncio
import logging
import time
from functools import lru_cache

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.core.service_auth import issue_service_token

logger = logging.getLogger(__name__)


class GatewayLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    context_limit: int = Field(gt=0)
    output_limit: int = Field(ge=0)
    tokenizer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parallel: int = Field(gt=0)
    deadline_seconds: float | None = Field(default=None, gt=0)
    build: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @model_validator(mode="after")
    def check_budget(self):
        if self.output_limit >= self.context_limit:
            raise ValueError("invalid_limits")
        return self


_cached: dict[str, tuple[float, GatewayLimits]] = {}


@lru_cache(maxsize=32)
def validate_timeouts(client: float, gateway: float | None, job: int, allowance: int) -> None:
    if (gateway is not None and client <= gateway) or job < client + allowance:
        logger.warning("ترتیب مهلت‌های پردازش رزومه ناسازگار است")


def check_worker_timeouts(gateway: float | None = None) -> None:
    validate_timeouts(
        settings.MODEL_INFERENCE_TIMEOUT_SECONDS,
        settings.MODEL_INFERENCE_GATEWAY_DEADLINE_SECONDS if gateway is None else gateway,
        settings.RESUME_JOB_TIMEOUT_SECONDS,
        settings.RESUME_EXTRACTION_PARSE_ALLOWANCE_SECONDS,
    )


async def fetch_limits() -> GatewayLimits | None:
    if not settings.MODEL_INFERENCE_LIMITS_SYNC or not settings.MODEL_INFERENCE_URL:
        return None
    url = settings.MODEL_INFERENCE_URL.rstrip("/")
    cached = _cached.get(url)
    if cached and time.monotonic() - cached[0] < settings.MODEL_INFERENCE_LIMITS_TTL_SECONDS:
        return cached[1]
    try:
        async with asyncio.timeout(2), httpx.AsyncClient(trust_env=False, timeout=2) as client:
            token = issue_service_token(audience="ats-inference")
            response = await client.get(url + "/v1/limits", headers={"X-Internal-Auth": token})
            response.raise_for_status()
            limits = GatewayLimits.model_validate_json(response.content)
    except Exception:
        return None
    check_worker_timeouts(limits.deadline_seconds)
    _cached[url] = (time.monotonic(), limits)
    return limits
