"""
عامل ۲ — اعتبارسنجی سوابق کاری (Experience Validation Agent).

پایه همان تحلیل‌گر سوابق خط لوله‌ی قبلی است (app/core/experience_analyzer.py: اعتبار هر بازه، دوره‌های نامعتبر).
این عامل روی آن اضافه می‌کند:
  - یکسان‌سازی شمسی/میلادی پیش از مقایسه (یک رزومه می‌تواند هر دو تقویم را داشته باشد)
  - تداخل‌های زمانی دوبه‌دو (کدام ردیف‌ها، چند سال)
  - سابقه‌ی خالص بعد از ادغام تداخل‌ها روی تقویم یکسان
  - هشدارهای بزرگ‌نمایی (کد، شدت، دلیل، تکه‌ی کوتاه متن):
      claimed_years_exceed_history  ادعای «N سال سابقه» خیلی بیشتر از سابقه‌ی قابل‌اثبات
      seniority_title_vs_tenure     عنوان ارشد/مدیر با سابقه‌ی کم
      concurrent_full_time_roles    بیش از دو شغل هم‌زمان
      skill_years_exceed_career     «N سال مهارت X» بیشتر از کل سابقه‌ی کاری
      invalid_period                بازه‌ی آینده/وارونه/غیرواقعی (همان قواعد تحلیل‌گر قبلی)
"""

import re

from app.agents.schema import ExperienceAgentOutput, ExperienceEntry, Flag, Overlap
from app.agents.text_signals import extract_claimed_total_years, extract_skill_year_claims
from app.core.experience_analyzer import (
    _SHAMSI_TO_GREGORIAN_OFFSET,
    _SHAMSI_YEAR_THRESHOLD,
    _merge_intervals_and_sum_years,
    analyze_work_experience,
)

AGENT_NAME = "experience_validation"

# حداقل سابقه‌ی معقول برای هر سطح عنوان شغلی (سال)
_SENIORITY_TITLE_MIN_YEARS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"\b(cto|vp|director|head of|principal)\b|مدیر فنی|مدیرعامل", re.I), 7.0, "مدیر ارشد/اصلی"),
    (re.compile(r"\b(lead|manager|architect)\b|سرپرست|مدیر|معمار", re.I), 5.0, "سرپرست/مدیر"),
    (re.compile(r"\b(senior|sr\.?)\b|ارشد", re.I), 3.0, "ارشد"),
]
_CLAIM_TOLERANCE_YEARS = 2.0
_MAX_CONCURRENT_ROLES = 2


def _gregorian(year: int | None) -> int | None:
    if year is None:
        return None
    return year + _SHAMSI_TO_GREGORIAN_OFFSET if year < _SHAMSI_YEAR_THRESHOLD else year


def _flag(code: str, severity: str, message: str, evidence: str | None = None) -> Flag:
    return Flag(code=code, severity=severity, message=message, evidence=evidence, source=AGENT_NAME)


def run_experience_agent(raw_text: str, parsed_data: dict | None, signals: dict | None = None) -> ExperienceAgentOutput:
    signals = signals or {}
    work_experience = (parsed_data or {}).get("work_experience") or []
    analysis = analyze_work_experience(work_experience)

    entries: list[ExperienceEntry] = []
    for index, entry in enumerate(analysis["entries"]):
        entries.append(
            ExperienceEntry(
                index=index,
                company=entry.get("company"),
                job_title=entry.get("job_title"),
                duration=entry.get("duration"),
                start_year=entry.get("start_year"),
                end_year=entry.get("end_year"),
                start_year_gregorian=_gregorian(entry.get("start_year")),
                end_year_gregorian=_gregorian(entry.get("end_year")),
                is_valid=bool(entry.get("is_valid")),
                flag_reason=entry.get("flag_reason"),
            )
        )

    valid = [entry for entry in entries if entry.is_valid and entry.start_year_gregorian is not None]
    total_years = _merge_intervals_and_sum_years([(e.start_year_gregorian, e.end_year_gregorian) for e in valid])

    overlaps: list[Overlap] = []
    for position, first in enumerate(valid):
        for second in valid[position + 1 :]:
            years = min(first.end_year_gregorian, second.end_year_gregorian) - max(
                first.start_year_gregorian, second.start_year_gregorian
            )
            if years > 0:
                overlaps.append(Overlap(entries=(first.index, second.index), years=float(years)))

    flags: list[Flag] = []
    invalid_periods = [entry.index for entry in entries if not entry.is_valid]
    for entry in entries:
        if not entry.is_valid:
            flags.append(_flag("invalid_period", "low", entry.flag_reason or "بازه‌ی تاریخ نامعتبر", entry.duration))

    claimed_total, claim_evidence = signals.get("claimed_total") or extract_claimed_total_years(raw_text)
    if claimed_total is not None and valid and claimed_total > total_years + _CLAIM_TOLERANCE_YEARS:
        gap = claimed_total - total_years
        flags.append(
            _flag(
                "claimed_years_exceed_history",
                "high" if gap >= 5 else "medium",
                f"ادعای {claimed_total:g} سال سابقه، ولی بازه‌های معتبر فقط {total_years:g} سال است.",
                claim_evidence,
            )
        )

    for entry in valid:
        title = entry.job_title or ""
        for pattern, min_years, level in _SENIORITY_TITLE_MIN_YEARS:
            if pattern.search(title):
                if total_years < min_years:
                    flags.append(
                        _flag(
                            "seniority_title_vs_tenure",
                            "medium",
                            f"عنوان «{level}» با کل سابقه‌ی {total_years:g} سال (حداقل معقول: {min_years:g}).",
                            title[:80],
                        )
                    )
                break

    # بیشترین تعداد شغل هم‌زمان در هر سال (بازه‌ها [شروع، پایان))
    if valid:
        years_range = range(min(e.start_year_gregorian for e in valid), max(e.end_year_gregorian for e in valid))
        peak = max(
            (sum(1 for e in valid if e.start_year_gregorian <= year < e.end_year_gregorian) for year in years_range),
            default=0,
        )
        if peak > _MAX_CONCURRENT_ROLES:
            flags.append(
                _flag("concurrent_full_time_roles", "medium", f"{peak} شغل هم‌زمان در یک بازه‌ی زمانی ثبت شده است.")
            )

    skill_claims = signals.get("skill_year_claims")
    if skill_claims is None:
        skill_claims = extract_skill_year_claims(raw_text)
    for skill, (years, evidence) in sorted(skill_claims.items()):
        if valid and years > total_years + _CLAIM_TOLERANCE_YEARS:
            flags.append(
                _flag(
                    "skill_years_exceed_career",
                    "high" if years - total_years >= 5 else "medium",
                    f"ادعای {years:g} سال {skill}، بیشتر از کل سابقه‌ی کاری ({total_years:g} سال).",
                    evidence,
                )
            )

    return ExperienceAgentOutput(
        status="completed",
        entries=entries,
        total_experience_years=float(total_years),
        overlaps=overlaps,
        invalid_periods=invalid_periods,
        claimed_total_years=claimed_total,
        flags=flags,
    )
