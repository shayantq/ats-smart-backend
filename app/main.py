"""
نقطه ورود اصلی پلتفرم ATS Smart - بک‌اند
معماری: FastAPI (Async)
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.limiter import limiter
from app.core.redis_client import check_redis_connection, close_redis_connection
from app.routers import admin, applications, auth, candidates, health, jobs, resumes

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # اتصال به Redis پیش از آماده شدن کامل سرور بررسی می‌شود تا وضعیتش در
    # لاگ‌های سرور واضح باشد؛ در دسترس نبودن Redis باعث توقف بالا آمدن سرور
    # نمی‌شود (فقط کش/صف موقتاً غیرفعال می‌مانند)، چون وابستگی حیاتی API نیست.
    await check_redis_connection()
    yield
    await close_redis_connection()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="سیستم هوشمند جذب و استخدام و تحلیل رزومه",
    version="0.1.0",
    swagger_ui_parameters={"withCredentials": True},
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# فقط در حالت ذخیره‌سازی محلی (STORAGE_BACKEND=local) لازم است: فایل‌های آپلودشده
# (مثل رزومه‌ها) از مسیر MEDIA_BASE_URL در دسترس قرار می‌گیرند. در حالت S3 این
# mount بلااستفاده می‌ماند چون فایل‌ها مستقیماً از Object Storage سرو می‌شوند.
if settings.STORAGE_BACKEND == "local":
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.MEDIA_ROOT), name="media")

app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth")
app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin")
app.include_router(jobs.router, prefix=f"{settings.API_V1_PREFIX}/jobs")
app.include_router(applications.router, prefix=f"{settings.API_V1_PREFIX}/applications")
app.include_router(resumes.router, prefix=f"{settings.API_V1_PREFIX}/resumes")
app.include_router(candidates.router, prefix=f"{settings.API_V1_PREFIX}/candidates")


@app.get("/", tags=["Root"])
async def root() -> dict:
    return {"message": f"{settings.PROJECT_NAME} API is running."}
