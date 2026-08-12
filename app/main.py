"""
نقطه ورود اصلی پلتفرم ATS Smart - بک‌اند
معماری: FastAPI (Async)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.limiter import limiter
from app.routers import admin, auth, health, jobs

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="سیستم هوشمند جذب و استخدام و تحلیل رزومه",
    version="0.1.0",
    swagger_ui_parameters={"withCredentials": True},
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

app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth")
app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin")
app.include_router(jobs.router, prefix=f"{settings.API_V1_PREFIX}/jobs")


@app.get("/", tags=["Root"])
async def root() -> dict:
    return {"message": f"{settings.PROJECT_NAME} API is running."}
