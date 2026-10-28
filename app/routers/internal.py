"""
مسیرهای داخلی سرویس‌به‌سرویس — /api/v1/internal (Zero-Trust):

    GET /internal/whoami                                     هویت سرویس فراخوان (آزمون احراز هویت)
    GET /internal/applications/{id}/interview-profile        پروفایل بدون اطلاعات شخصی برای تولید سؤال مصاحبه

هر مسیر:
    ۱. فقط از داخل شبکه‌ی سرویس‌ها: درخواستی که از Gateway/Ingress عمومی رد شده (X-Forwarded-For دارد) ← 404،
       یعنی این مسیرها از اینترنت وجود ندارند.
    ۲. توکن سرویس معتبر در X-Internal-Auth (app/core/service_auth.py) ← وگرنه 401.
    ۳. داده با RLS به سازمانِ داخل توکن (tid) محدود است — سرویس داخلی هم به همه‌ی سازمان‌ها دسترسی ندارد.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.service_auth import BACKEND_AUDIENCE, ServiceClaims, require_service_token
from app.core.tenancy import SCOPE_TENANT, TenantContext, apply_current_context, use_tenant_context
from app.db.session import get_db
from app.genai.service import build_profile_for_application
from app.models import Application

# سرویس‌هایی که اجازه دارند پروفایل مصاحبه را بخوانند: Worker عمومی (Compose) و genai-worker (Kubernetes)
PROFILE_READERS = ("worker", "genai-worker")


async def reject_public_edge(request: Request) -> None:
    if request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(dependencies=[Depends(reject_public_edge)])


@router.get("/whoami", tags=["Internal"], summary="هویت سرویس فراخوان (آزمون توکن سرویس)")
async def whoami(
    claims: ServiceClaims = Depends(require_service_token(*PROFILE_READERS, audience=BACKEND_AUDIENCE))
) -> dict:
    return {
        "service": claims.issuer,
        "audience": claims.audience,
        "tenant_id": str(claims.tenant_id) if claims.tenant_id else None,
        "expires_at": claims.expires_at,
    }


@router.get(
    "/applications/{application_id}/interview-profile",
    tags=["Internal"],
    summary="پروفایل بدون اطلاعات شخصی کارجو برای تولید سؤال مصاحبه (سرویس هوش مصنوعی ← سرویس رزومه)",
)
async def interview_profile(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: ServiceClaims = Depends(require_service_token(*PROFILE_READERS, audience=BACKEND_AUDIENCE)),
) -> dict:
    if claims.tenant_id is None:
        # توکن بدون سازمان ← دسترسی حداقلی: هیچ داده‌ی سازمانی خوانده نمی‌شود
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="توکن سرویس به سازمانی محدود نشده است.")
    with use_tenant_context(TenantContext(SCOPE_TENANT, tenant_id=claims.tenant_id)):
        await apply_current_context(db)
        application = (
            await db.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if application is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="درخواست یافت نشد.")
        profile = await build_profile_for_application(db, application)
    return {"application_id": str(application_id), "profile": profile}
