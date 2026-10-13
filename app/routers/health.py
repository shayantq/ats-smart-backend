import asyncio

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.db.session import get_db
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()

READINESS_TIMEOUT_SECONDS = 2


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="بررسی سلامت سرور",
    tags=["Health"],
)
async def health_check() -> HealthResponse:
    """
    اندپوینت سبک (Liveness) برای اطمینان از بالا بودن پردازه‌ی بک‌اند — Healthcheck داکر و
    استقرار بدون قطعی به همین تکیه می‌کنند. عمداً به دیتابیس/Redis وابسته نیست تا قطعی
    موقت آن‌ها باعث ری‌استارت پشت‌سرهم کانتینرها نشود.
    """
    return HealthResponse(status="ok", project=settings.PROJECT_NAME, version=settings.APP_VERSION)


async def _check_database(db: AsyncSession) -> str:
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), READINESS_TIMEOUT_SECONDS)
        return "ok"
    except Exception:  # noqa: BLE001 - هر خطایی یعنی «آماده نیست»
        return "unavailable"


async def _check_redis() -> str:
    try:
        await asyncio.wait_for(get_redis_client().ping(), READINESS_TIMEOUT_SECONDS)
        return "ok"
    except Exception:  # noqa: BLE001
        return "unavailable"


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "یکی از وابستگی‌ها در دسترس نیست"}},
    summary="آمادگی کامل سرویس (دیتابیس + Redis)",
    tags=["Health"],
)
async def readiness_check(response: Response, db: AsyncSession = Depends(get_db)) -> ReadinessResponse:
    """
    بررسی عمیق (Readiness): اتصال واقعی به PostgreSQL و Redis. برای Sanity Check پس از
    استقرار و پایش بیرونی — اگر هرکدام در دسترس نباشد، پاسخ 503 با جزئیات برمی‌گردد.
    """
    checks = {"database": await _check_database(db), "redis": await _check_redis()}
    ready = all(result == "ok" for result in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if ready else "degraded", version=settings.APP_VERSION, checks=checks)
