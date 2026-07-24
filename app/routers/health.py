from fastapi import APIRouter, status

from app.core.config import settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="بررسی سلامت سرور",
    tags=["Health"],
)
async def health_check() -> HealthResponse:
    """اندپوینت سبک برای اطمینان از باال بودن سرویس بک‌اند."""
    return HealthResponse(status="ok", project=settings.PROJECT_NAME, version="0.1.0")
