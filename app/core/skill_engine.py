"""
موتور استخراج مهارت‌ها و تحلیل سوابق کاری (Skill Engine) — مرحله‌ی سوم خط
لوله‌ی هوش مصنوعی، بلافاصله بعد از مرحله‌ی NER (app/core/resume_parser.py).

ورودی: متن خام رزومه (raw_text) + لیست تجربیات شغلی استخراج‌شده در مرحله‌ی NER.
خروجی: مهارت‌های تطبیق‌یافته با گراف مهارت (app/core/skill_graph.py) + تحلیل
خالص سال‌های سابقه‌ی کاری (app/core/experience_analyzer.py، با کسر تداخل‌های
زمانی و فیلتر دوره‌های نامعتبر/بزرگ‌نمایی‌شده).
"""

from app.core.experience_analyzer import analyze_work_experience
from app.core.skill_graph import match_skills


def run_skill_engine(raw_text: str, work_experience: list[dict]) -> dict:
    """
    نقطه‌ی ورود اصلی موتور مهارت. خروجی یک دیکشنری آماده برای ذخیره در ستون
    JSONB جدید skill_analysis از جدول resumes است:

    {
        "skills": ["Python", "FastAPI", ...],
        "total_experience_years": 4.5,
        "experience_entries": [
            {"company": "...", "job_title": "...", "duration": "...",
             "start_year": 1398, "end_year": 1401, "is_valid": true, "flag_reason": null},
            ...
        ]
    }
    """
    skills = match_skills(raw_text)
    experience_analysis = analyze_work_experience(work_experience)

    return {
        "skills": skills,
        "total_experience_years": experience_analysis["total_experience_years"],
        "experience_entries": experience_analysis["entries"],
    }
