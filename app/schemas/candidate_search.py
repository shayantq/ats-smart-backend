"""
اسکیمای خروجی موتور جستجوی پیشرفته‌ی کارجویان (HR):
GET /api/v1/candidates/search/
"""

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class CandidateSearchItem(BaseModel):
    """یک ردیف از نتایج جستجو — خلاصه‌ای از پروفایل کارجو به‌همراه بهترین سیگنال‌های هوش مصنوعی موجود."""

    candidate_id: uuid.UUID = Field(validation_alias="id")
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    location: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    # بالاترین نمره‌ی هوش مصنوعی (score_ai) در میان تمام درخواست‌های این کارجو —
    # None یعنی هنوز هیچ رزومه‌ای از این کارجو کامل پردازش/نمره‌دهی نشده است.
    best_ai_score: Optional[int] = None
    # بیشترین «سال‌های سابقه‌ی کاری خالص» استخراج‌شده در میان رزومه‌های این کارجو
    # (خروجی موتور مهارت — app/core/skill_engine.py).
    best_experience_years: Optional[float] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class CandidateSearchResponse(BaseModel):
    """پاسخ موتور جستجو — صفحه‌بندی مبتنی بر نشانگر (Cursor Pagination)."""

    items: list[CandidateSearchItem]
    next_cursor: Optional[str] = None
    previous_cursor: Optional[str] = None
    has_next: bool = False
    has_previous: bool = False
