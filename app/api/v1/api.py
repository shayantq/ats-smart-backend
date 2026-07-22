from fastapi import APIRouter

from app.api.v1.endpoints import health

api_router = APIRouter()

# در اسپرینت‌های بعدی، روترهای auth, jobs, resumes, applications و ... در همینجا اضافه می‌شوند
api_router.include_router(health.router)
