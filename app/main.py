"""
نقطه ورود اصلی پلتفرم ATS Smart - بک‌اند
معماری: FastAPI (Async) طبق مستند فنی پروژه، بخش ۴ و ۶
"""

from fastapi import FastAPI

from app.api.v1.api import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="سیستم هوشمند جذب و استخدام و تحلیل رزومه",
    version="0.1.0",
)

# ثبت روترهای نسخه ۱ خطوط ارتباطی (API v1)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Root"])
async def root() -> dict:
    return {"message": f"{settings.PROJECT_NAME} API is running."}
