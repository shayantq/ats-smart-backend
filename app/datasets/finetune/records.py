"""
ساخت یک رکورد دیتاست (instruction / input / output) از یک جفت «رزومه ↔ آگهی».

output کاملاً قطعی (Deterministic) از خروجی اکوسیستم چندعاملی (agent_analysis، قرارداد agents-v1) و نمره‌ی
ذخیره‌شده‌ی درخواست (score_ai) ساخته می‌شود — هیچ مدل زبانی در تولید برچسب نقشی ندارد. نتیجه‌ی واقعی HR
(وضعیت نهایی درخواست و میانگین نمره‌ی مصاحبه) هم وقتی وجود دارد اضافه می‌شود.

عمداً حذف‌شده از output: evidence هشدارها و عبارت‌های شاهد مهارت‌های نرم (تکه‌ی خام متن رزومه‌اند)، شناسه‌های
داخلی و زمان‌بندی عامل‌ها.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.datasets.finetune.anonymize import Identity, Redactor
from app.datasets.finetune.text_clean import normalize_text

INSTRUCTION_VERSION = "hr-eval-v1"
INSTRUCTION = (
    "شما کارشناس ارشد جذب و استخدام در بازار کار ایران هستید. رزومه‌ی زیر را با آگهی شغلی مقایسه و ارزیابی کنید. "
    "پاسخ را فقط به‌صورت یک شیء JSON با این کلیدها برگردانید: score (عدد صحیح 0 تا 100)، verdict، matched_skills، "
    "missing_skills، experience، soft_skills، flags، hr_outcome و rationale. اطلاعات هویتی کارجو با برچسب‌هایی مثل "
    "[NAME]، [EMAIL] و [PHONE] جایگزین شده است؛ آن‌ها را حدس نزنید و در ارزیابی دخالت ندهید."
)

STRONG_MATCH_SCORE = 70
POTENTIAL_MATCH_SCORE = 40
SOFT_SKILL_MIN_SCORE = 0.5
MAX_SOFT_SKILLS = 5
MAX_POSITIONS = 10
OUTCOME_STATUSES_EXCLUDED = frozenset({"Draft"})


@dataclass(frozen=True)
class JobInfo:
    title: str = ""
    department: str | None = None
    description: str | None = None
    skills_required: tuple[str, ...] = ()
    seniority: str | None = None
    education: str | None = None


@dataclass(frozen=True)
class PairSource:
    """یک جفت خام از دیتابیس (رمزگشایی‌شده، فقط در حافظه). candidate_key فقط برای گروه‌بندی تقسیم است."""

    candidate_key: str
    score_ai: int | None
    status: str
    job: JobInfo
    resume_text: str | None
    analysis: dict | None
    identity: Identity = field(default_factory=Identity)
    interview_score: float | None = None
    # کارجو در همان سازمان چند رزومه‌ی پردازش‌شده دارد و هیچ‌کدام (یا بیش از یکی) با نمره‌ی همین درخواست
    # جور نیست — نمی‌دانیم کدام رزومه برای این آگهی فرستاده شده؛ رکورد کنار گذاشته می‌شود
    ambiguous_link: bool = False


def verdict_for(score: int) -> str:
    if score >= STRONG_MATCH_SCORE:
        return "مناسب"
    if score >= POTENTIAL_MATCH_SCORE:
        return "نیازمند بررسی بیشتر"
    return "نامناسب"


def _job_block(job: JobInfo, redactor: Redactor) -> str:
    lines = [f"عنوان: {job.title}"]
    optional = (
        ("دپارتمان", job.department),
        ("سطح ارشدیت", job.seniority),
        ("تحصیلات لازم", job.education),
    )
    lines += [f"{label}: {value}" for label, value in optional if value]
    if job.skills_required:
        lines.append("مهارت‌های لازم: " + "، ".join(job.skills_required))
    if job.description:
        lines.append("شرح:\n" + job.description)
    return redactor.other_text(normalize_text("\n".join(lines)))


def build_input(source: PairSource, resume_text: str, redactor: Redactor) -> str:
    return f"## آگهی شغلی\n{_job_block(source.job, redactor)}\n\n## رزومه\n{resume_text}"


def _skills(analysis: dict, job: JobInfo) -> tuple[list[str], list[str]]:
    required = list(dict.fromkeys(skill.strip() for skill in job.skills_required if skill and skill.strip()))
    reported = {name.lower() for name in (analysis.get("matching") or {}).get("matched_required_skills") or []}
    if not reported:
        items = (analysis.get("skills") or {}).get("items") or []
        reported = {str(item.get(key, "")).lower() for item in items for key in ("name", "core")}
    matched = [skill for skill in required if skill.lower() in reported]
    missing = [skill for skill in required if skill.lower() not in reported]
    return matched, missing


def _experience(analysis: dict, redactor: Redactor) -> dict:
    experience = analysis.get("experience") or {}
    positions = []
    for entry in (experience.get("entries") or [])[:MAX_POSITIONS]:
        if not entry.get("is_valid"):
            continue
        position = {key: entry.get(key) for key in ("job_title", "company", "duration") if entry.get(key)}
        positions.append({key: redactor.other_text(normalize_text(str(value))) for key, value in position.items()})
    return {
        "total_years": round(float(experience.get("total_experience_years") or 0.0), 1),
        "positions": positions,
        "overlaps": len(experience.get("overlaps") or []),
        "invalid_periods": len(experience.get("invalid_periods") or []),
    }


def _soft_skills(analysis: dict, redactor: Redactor) -> list[str]:
    items = (analysis.get("soft_skills") or {}).get("items") or []
    strong = [item for item in items if float(item.get("score") or 0) >= SOFT_SKILL_MIN_SCORE]
    strong.sort(key=lambda item: (-float(item["score"]), item.get("key", "")))
    labels = (normalize_text(item.get("label_fa") or item.get("key", "")) for item in strong[:MAX_SOFT_SKILLS])
    return [redactor.other_text(label) for label in labels]


def _flags(analysis: dict, redactor: Redactor) -> list[dict]:
    flags = []
    for flag in analysis.get("flags") or []:
        message = redactor.other_text(normalize_text(flag.get("message") or ""))
        flags.append({"code": flag.get("code"), "severity": flag.get("severity"), "message": message})
    return flags


def _hr_outcome(source: PairSource) -> dict | None:
    status = source.status if source.status not in OUTCOME_STATUSES_EXCLUDED else None
    if status is None and source.interview_score is None:
        return None
    interview = round(source.interview_score, 2) if source.interview_score is not None else None
    return {"status": status, "interview_score": interview}


def _rationale(score: int, matched: list[str], missing: list[str], experience: dict, flags: list[dict]) -> str:
    total = len(matched) + len(missing)
    parts = [f"نمره‌ی تطابق {score} از 100 ({verdict_for(score)})."]
    if total:
        parts.append(f"{len(matched)} از {total} مهارت لازم آگهی در رزومه دیده شد.")
    if missing:
        parts.append("مهارت‌های غایب: " + "، ".join(missing) + ".")
    parts.append(f"سابقه‌ی کاری معتبر: {experience['total_years']} سال.")
    if flags:
        parts.append(f"{len(flags)} هشدار اعتبارسنجی برای بررسی HR ثبت شد.")
    return " ".join(parts)


def build_output(source: PairSource, redactor: Redactor) -> str:
    analysis = source.analysis or {}
    score = int(source.score_ai)
    matched, missing = _skills(analysis, source.job)
    experience = _experience(analysis, redactor)
    flags = _flags(analysis, redactor)
    payload = {
        "score": score,
        "verdict": verdict_for(score),
        "matched_skills": matched,
        "missing_skills": missing,
        "experience": experience,
        "soft_skills": _soft_skills(analysis, redactor),
        "flags": flags,
        "hr_outcome": _hr_outcome(source),
        "rationale": _rationale(score, matched, missing, experience, flags),
    }
    return json.dumps(payload, ensure_ascii=False)


def build_record(source: PairSource, resume_text: str, redactor: Redactor) -> dict[str, str]:
    """resume_text باید قبلاً نرمال و ناشناس شده باشد (cleanse.py)."""
    return {
        "instruction": INSTRUCTION,
        "input": build_input(source, resume_text, redactor),
        "output": build_output(source, redactor),
    }
