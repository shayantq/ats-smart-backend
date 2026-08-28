"""
اسکیمای خروجی ماژول پارسینگ متنی و بازشناسی موجودیت‌های نامدار (NER).

این‌ها فقط برای شکل‌دهی و اعتبارسنجی خروجی داخلی موتور پارسینگ
(app/core/resume_parser.py) هستند؛ خروجی نهایی همین ساختار، به‌صورت JSON،
در ستون parsed_data جدول resumes ذخیره می‌شود تا به مرحله‌ی بعدی خط لوله
(امتیازدهی هوش مصنوعی) منتقل شود.
"""

from typing import Optional

from pydantic import BaseModel, Field


class PersonalInfo(BaseModel):
    """اطلاعات فردی استخراج‌شده از رزومه."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class WorkExperienceEntry(BaseModel):
    """یک ردیف تجربه‌ی شغلی استخراج‌شده."""

    company: Optional[str] = None
    job_title: Optional[str] = None
    duration: Optional[str] = None


class EducationEntry(BaseModel):
    """یک ردیف سابقه‌ی تحصیلی استخراج‌شده."""

    degree: Optional[str] = None
    university: Optional[str] = None
    gpa: Optional[float] = None


class ParsedResumeData(BaseModel):
    """خروجی کامل و نهایی ماژول NER برای یک رزومه."""

    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    education: list[EducationEntry] = Field(default_factory=list)
    work_experience: list[WorkExperienceEntry] = Field(default_factory=list)
