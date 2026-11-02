"""
عامل ناظر (Supervisor Agent) — دو نقش در گراف (app/agents/graph.py):

۱. توزیع (dispatch): فایل خام رزومه را می‌گیرد، متن را «یک‌بار» استخراج (OCR در صورت نیاز) و «یک‌بار» پارس
   (NER) می‌کند و همان ورودی مشترک را هم‌زمان به سه عامل تخصصی می‌دهد.
۲. جمع‌بندی (aggregate): خروجی سه عامل را یکی می‌کند، تعارض‌ها را با قواعد صریح زیر حل و ثبت می‌کند و نمره‌ی
   نهایی تطابق را می‌سازد. خروجی همیشه با قرارداد UnifiedAnalysis (app/agents/schema.py) اعتبارسنجی می‌شود.

قواعد حل تعارض:
  R1 skill_years_capped        ادعای «N سال مهارت X» (عامل مهارت) بیشتر از سابقه‌ی تأییدشده (عامل سوابق) ← سقف =
                               سابقه‌ی تأییدشده، و اطمینان آن مهارت × ۰٫۷
  R2 claimed_total_overridden  ادعای «N سال سابقه» در متن با سابقه‌ی محاسبه‌شده از بازه‌ها جایگزین می‌شود
  R3 leadership_unsupported    مهارت نرم «رهبری» (عامل مهارت نرم) بدون هیچ عنوان سرپرستی/مدیریتی و با سابقه‌ی
                               کمتر از ۳ سال (عامل سوابق) ← امتیاز رهبری نصف
  R4 agent_failed              عاملی شکست خورده/زمانش تمام شده ← بخشش «failed» و وضعیت کل «partial»؛ نمره با
                               داده‌ی موجود (بدون مهارت = مؤلفه‌ی مهارت صفر)

نمره‌ی نهایی = موتور نمره‌دهی قبلی (app/core/matching_engine.py، همان مؤلفه‌ها و وزن‌ها) روی داده‌ی یکپارچه
             + پاداش مهارت نرم (حداکثر +۵) − جریمه‌ی هشدارهای اعتبارسنجی (high ۶، medium ۳، low ۱؛ حداکثر −۱۵)
             ← محدود به ۰ تا ۱۰۰
"""

import re

from app.agents.schema import (
    ConflictResolution,
    ExperienceAgentOutput,
    Matching,
    SkillAgentOutput,
    SoftSkillsAgentOutput,
    UnifiedAnalysis,
    UnifiedExperience,
    UnifiedSkills,
    UnifiedSoftSkills,
)
from app.core.matching_engine import calculate_matching_score
from app.core.resume_parser import parse_resume_text
from app.core.text_extraction import extract_raw_text

SKILL_AGENT = "skill_extraction"
EXPERIENCE_AGENT = "experience_validation"
SOFT_SKILLS_AGENT = "culture_fit_soft_skills"
AGENTS = (SKILL_AGENT, EXPERIENCE_AGENT, SOFT_SKILLS_AGENT)

SOFT_SKILL_MAX_BONUS = 5.0
VALIDATION_PENALTY = {"high": 6.0, "medium": 3.0, "low": 1.0}
VALIDATION_MAX_PENALTY = 15.0
_CLAIM_TOLERANCE_YEARS = 2.0
_CAPPED_SKILL_CONFIDENCE_FACTOR = 0.7
_LEADERSHIP_MIN_YEARS = 3.0
_LEADERSHIP_TITLE = re.compile(r"\b(lead|manager|head|director|cto|vp|principal|supervisor)\b|سرپرست|مدیر|راهبر", re.I)


def dispatch(file_bytes: bytes, filename: str) -> tuple[str, dict | None, str | None]:
    """ورودی مشترک سه عامل: (متن خام، داده‌ی ساختاریافته یا None، خطای پارس یا None). خطای استخراج متن بالا می‌رود."""
    raw_text = extract_raw_text(file_bytes, filename=filename)
    try:
        return raw_text, parse_resume_text(raw_text).model_dump(), None
    except Exception as error:  # noqa: BLE001 - شکست پارس نباید عامل‌های متن‌محور را متوقف کند
        return raw_text, None, type(error).__name__


def _failed(model, payload, default_error: str):
    """خروجی عامل (مدل Pydantic یا dict) ← همان مدل؛ نبود خروجی یا شکست ← نسخه‌ی «failed» همان مدل."""
    if isinstance(payload, model) and payload.status == "completed":
        return payload
    if isinstance(payload, dict) and payload.get("status") == "completed":
        return model.model_validate(payload)
    error = payload.get("error") if isinstance(payload, dict) else getattr(payload, "error", None)
    return model(status="failed", error=error or default_error)


def aggregate(
    *,
    skill_payload: dict | None,
    experience_payload: dict | None,
    soft_payload: dict | None,
    parsed_data: dict | None,
    job_context: dict | None,
    timings: dict,
    errors: dict,
) -> UnifiedAnalysis:
    skills = _failed(SkillAgentOutput, skill_payload, "no_output")
    experience = _failed(ExperienceAgentOutput, experience_payload, "no_output")
    soft = _failed(SoftSkillsAgentOutput, soft_payload, "no_output")
    conflicts: list[ConflictResolution] = []
    errors = dict(errors)

    for name, output in ((SKILL_AGENT, skills), (EXPERIENCE_AGENT, experience), (SOFT_SKILLS_AGENT, soft)):
        if output.status == "failed":
            errors.setdefault(name, output.error or "failed")
            conflicts.append(
                ConflictResolution(
                    code="agent_failed",
                    agents=[name],
                    description=f"عامل {name} خروجی نداد ({errors[name]}).",
                    resolution="بخش این عامل «failed» علامت خورد؛ جمع‌بندی و نمره با خروجی بقیه‌ی عامل‌ها انجام شد.",
                )
            )

    validated_years = experience.total_experience_years if experience.status == "completed" else 0.0
    has_history = experience.status == "completed" and any(entry.is_valid for entry in experience.entries)

    # R1: ادعای سال برای مهارت بیشتر از کل سابقه‌ی تأییدشده
    skill_items = []
    for item in skills.skills:
        if (
            has_history
            and item.claimed_years is not None
            and item.claimed_years > validated_years + _CLAIM_TOLERANCE_YEARS
        ):
            conflicts.append(
                ConflictResolution(
                    code="skill_years_capped",
                    agents=[SKILL_AGENT, EXPERIENCE_AGENT],
                    description=(
                        f"ادعای {item.claimed_years:g} سال {item.name} در برابر "
                        f"{validated_years:g} سال سابقه‌ی تأییدشده."
                    ),
                    resolution=(
                        f"سال‌های {item.name} به {validated_years:g} محدود و "
                        f"اطمینانش ×{_CAPPED_SKILL_CONFIDENCE_FACTOR} شد."
                    ),
                )
            )
            item = item.model_copy(
                update={
                    "claimed_years": float(validated_years),
                    "confidence": round(item.confidence * _CAPPED_SKILL_CONFIDENCE_FACTOR, 2),
                }
            )
        skill_items.append(item)

    # R2: ادعای کل سابقه در متن ← سابقه‌ی محاسبه‌شده از بازه‌ها مرجع است
    if (
        has_history
        and experience.claimed_total_years is not None
        and experience.claimed_total_years > validated_years + _CLAIM_TOLERANCE_YEARS
    ):
        conflicts.append(
            ConflictResolution(
                code="claimed_total_overridden",
                agents=[EXPERIENCE_AGENT],
                description=(
                    f"متن رزومه {experience.claimed_total_years:g} سال سابقه ادعا می‌کند؛ "
                    f"بازه‌های معتبر {validated_years:g} سال."
                ),
                resolution="سابقه‌ی محاسبه‌شده از بازه‌های تاریخ (پس از ادغام تداخل‌ها) مرجع نمره‌دهی است.",
            )
        )

    # R3: رهبری بدون پشتوانه‌ی عنوان و سابقه
    soft_items = list(soft.soft_skills)
    if experience.status == "completed":
        has_lead_title = any(_LEADERSHIP_TITLE.search(entry.job_title or "") for entry in experience.entries)
        for position, item in enumerate(soft_items):
            if item.key == "leadership" and not has_lead_title and validated_years < _LEADERSHIP_MIN_YEARS:
                soft_items[position] = item.model_copy(update={"score": round(item.score / 2, 2)})
                conflicts.append(
                    ConflictResolution(
                        code="leadership_unsupported",
                        agents=[SOFT_SKILLS_AGENT, EXPERIENCE_AGENT],
                        description="نشانه‌های «رهبری» در متن، بدون عنوان سرپرستی/مدیریتی و با سابقه‌ی کمتر از ۳ سال.",
                        resolution="امتیاز مهارت نرم رهبری نصف شد.",
                    )
                )

    flags = list(experience.flags)
    matching = _matching(skill_items, experience, validated_years, soft_items, soft, flags, parsed_data, job_context)

    failed = [name for name in AGENTS if name in errors]
    status = "completed" if not failed else ("failed" if len(failed) == len(AGENTS) else "partial")
    return UnifiedAnalysis(
        status=status,
        skills=UnifiedSkills(status=skills.status, items=skill_items),
        experience=UnifiedExperience(
            status=experience.status,
            total_experience_years=float(validated_years),
            entries=experience.entries,
            overlaps=experience.overlaps,
            invalid_periods=experience.invalid_periods,
        ),
        soft_skills=UnifiedSoftSkills(status=soft.status, items=soft_items, tone=soft.tone, confidence=soft.confidence),
        conflicts_resolved=conflicts,
        flags=flags,
        matching=matching,
        errors=errors,
        timings_ms=timings,
    )


def _matching(skill_items, experience, validated_years, soft_items, soft, flags, parsed_data, job_context) -> Matching:
    if not job_context:
        return Matching()
    parsed = parsed_data or {}
    base = calculate_matching_score(
        job_skills_required=job_context.get("skills_required"),
        job_title=job_context.get("title") or "",
        job_required_seniority=job_context.get("required_seniority"),
        job_required_education=job_context.get("required_education"),
        job_location=job_context.get("location"),
        job_description=job_context.get("description"),
        candidate_skills=[item.name for item in skill_items],
        candidate_job_titles=[e.get("job_title") for e in parsed.get("work_experience", []) if e.get("job_title")],
        candidate_total_experience_years=float(validated_years),
        candidate_education_entries=parsed.get("education", []),
        candidate_location=job_context.get("candidate_location"),
    )
    top_scores = sorted((item.score for item in soft_items), reverse=True)[:3]
    bonus = 0.0
    if top_scores:
        bonus = SOFT_SKILL_MAX_BONUS * (sum(top_scores) / len(top_scores)) * max(0.5, soft.confidence)
    penalty = min(VALIDATION_MAX_PENALTY, sum(VALIDATION_PENALTY[flag.severity] for flag in flags))
    score = max(0.0, min(100.0, round(base["final_score"] + bonus - penalty, 2)))
    return Matching(
        score=score,
        base_score=base["final_score"],
        components=base["breakdown"],
        soft_skill_bonus=round(bonus, 2),
        validation_penalty=round(penalty, 2),
        matched_required_skills=base["matched_required_skills"],
    )


def to_skill_analysis(analysis: UnifiedAnalysis) -> dict:
    """همان شکل ستون skill_analysis خط لوله‌ی قبلی (جستجو، ایندکس مهارت/سابقه و UI بدون تغییر)."""
    return {
        "skills": sorted({item.name for item in analysis.skills.items}),
        "total_experience_years": analysis.experience.total_experience_years,
        "experience_entries": [
            {
                "company": entry.company,
                "job_title": entry.job_title,
                "duration": entry.duration,
                "start_year": entry.start_year,
                "end_year": entry.end_year,
                "is_valid": entry.is_valid,
                "flag_reason": entry.flag_reason,
            }
            for entry in analysis.experience.entries
        ],
    }
