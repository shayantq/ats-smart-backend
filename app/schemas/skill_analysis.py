"""اسکیمای خروجی موتور مهارت (Skill Engine) — app/core/skill_engine.py."""

from typing import Optional

from pydantic import BaseModel, Field


class ExperienceEntryAnalysis(BaseModel):
    """یک ردیف تجربه‌ی شغلی، بعد از اعتبارسنجی دوره‌ی زمانی‌اش."""

    company: Optional[str] = None
    job_title: Optional[str] = None
    duration: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    is_valid: bool
    flag_reason: Optional[str] = None


class SkillAnalysisResult(BaseModel):
    """خروجی کامل و نهایی موتور مهارت برای یک رزومه."""

    skills: list[str] = Field(default_factory=list)
    total_experience_years: float = 0.0
    experience_entries: list[ExperienceEntryAnalysis] = Field(default_factory=list)
