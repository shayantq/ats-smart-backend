from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    project: str
    version: str


class ReadinessResponse(BaseModel):
    status: str  # "ok" | "degraded"
    version: str
    checks: dict[str, str]  # {"database": "ok" | "unavailable", "redis": ...}
