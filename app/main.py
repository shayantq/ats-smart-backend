"""
نقطه ورود اصلی پلتفرم ATS Smart - بک‌اند
معماری: FastAPI (Async)
"""

from fastapi import FastAPI

from app.core.config import settings
from app.routers import admin, auth, health

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="سیستم هوشمند جذب و استخدام و تحلیل رزومه",
    version="0.1.0",
    # بدون این تنظیم، Swagger UI کوکی‌های HttpOnly (مثل refresh_token) را
    # هنگام تست از طریق دکمه‌ی Execute در مرورگر ذخیره نمی‌کند.
    swagger_ui_parameters={"withCredentials": True},
)

app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth")
app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin")


@app.get("/", tags=["Root"])
async def root() -> dict:
    return {"message": f"{settings.PROJECT_NAME} API is running."}
