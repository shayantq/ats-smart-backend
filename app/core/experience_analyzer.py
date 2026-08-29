"""
تحلیل‌گر سوابق کاری: محاسبه‌ی مجموع سال‌های سابقه‌ی کاری خالص (Net Experience)
با کسر تداخل‌های زمانی (Overlaps)، و فیلتر کردن دوره‌های زمانی نامعتبر،
متناقض، یا بزرگ‌نمایی‌شده (تسک: موتور استخراج مهارت‌ها و تشخیص سوابق کاری).

ورودی این ماژول، لیست تجربیات شغلی خروجی مرحله‌ی NER (app/core/resume_parser.py)
است — هر ردیف شامل company، job_title و duration (رشته‌ای مثل "1398 - 1401"
یا "1401 - تاکنون").
"""

import datetime
import logging
import re

logger = logging.getLogger("ats_smart.experience_analyzer")

_YEAR_PATTERN = re.compile(r"\d{3,4}")
_CURRENT_MARKERS = ("تاکنون", "اکنون", "حال حاضر", "present", "current")

# اگر سال کمتر از این آستانه باشد، تقویم شمسی فرض می‌شود (سال‌های ۱۳XX/۱۴XX)؛
# در غیر این صورت تقویم میلادی (۱۹XX/۲۰XX) فرض می‌شود.
_SHAMSI_YEAR_THRESHOLD = 1500

# اگر طول یک تجربه‌ی شغلی از این تعداد سال بیشتر باشد، غیرواقعی/بزرگ‌نمایی‌شده
# تلقی و فیلتر می‌شود (هیچ شغل واحدی منطقاً این‌قدر طول نمی‌کشد).
_MAX_REASONABLE_SINGLE_JOB_YEARS = 40

# تفاوت تقریبی سال شمسی و میلادی — برای این سطح از تحلیل (رد کردن تاریخ‌های
# آینده) دقت کافی است و نیازی به تبدیل تقویم دقیق (با احتساب کبیسه) نیست.
_SHAMSI_TO_GREGORIAN_OFFSET = 621


def _current_year_for_calendar(is_shamsi: bool) -> int:
    gregorian_now = datetime.date.today().year
    return gregorian_now - _SHAMSI_TO_GREGORIAN_OFFSET if is_shamsi else gregorian_now


def _parse_duration(duration: str | None) -> tuple[int, int] | None:
    """رشته‌ی duration (مثل «1398 - 1401» یا «1401 - تاکنون») را به (سال شروع، سال پایان) تبدیل می‌کند."""
    if not duration:
        return None

    parts = re.split(r"[-–—]", duration, maxsplit=1)
    if len(parts) != 2:
        return None

    start_part, end_part = parts[0].strip(), parts[1].strip()

    start_match = _YEAR_PATTERN.search(start_part)
    if not start_match:
        return None
    start_year = int(start_match.group(0))

    is_shamsi = start_year < _SHAMSI_YEAR_THRESHOLD
    lowered_end_part = end_part.lower()

    if any(marker in end_part or marker in lowered_end_part for marker in _CURRENT_MARKERS):
        end_year = _current_year_for_calendar(is_shamsi)
    else:
        end_match = _YEAR_PATTERN.search(end_part)
        if not end_match:
            return None
        end_year = int(end_match.group(0))

    return start_year, end_year


def _validate_entry(start_year: int, end_year: int, is_shamsi: bool) -> str | None:
    """
    دوره‌ی زمانی یک تجربه‌ی شغلی را اعتبارسنجی می‌کند. اگر نامعتبر/متناقض/
    بزرگ‌نمایی‌شده بود، دلیل رد شدنش را برمی‌گرداند؛ اگر معتبر بود None.
    """
    current_year = _current_year_for_calendar(is_shamsi)

    if end_year < start_year:
        return "تاریخ پایان قبل از تاریخ شروع است (دوره‌ی زمانی متناقض)."

    if start_year > current_year or end_year > current_year:
        return "تاریخ در آینده است (احتمالاً نادرست)."

    if (end_year - start_year) > _MAX_REASONABLE_SINGLE_JOB_YEARS:
        return f"طول این دوره ({end_year - start_year} سال) غیرواقعی/بزرگ‌نمایی‌شده به نظر می‌رسد."

    return None


def _merge_intervals_and_sum_years(intervals: list[tuple[int, int]]) -> float:
    """
    الگوریتم استاندارد ادغام بازه‌های همپوشان (Merge Intervals): بازه‌ها را بر
    اساس سال شروع مرتب می‌کند، بازه‌های همپوشان/چسبیده را در هم ادغام می‌کند،
    و مجموع طول بازه‌های نهایی (بدون هیچ تداخلی) را برمی‌گرداند — این دقیقاً
    همان «سابقه‌ی کاری خالص» است که دو شغل هم‌زمان را دوبار حساب نمی‌کند.
    """
    if not intervals:
        return 0.0

    sorted_intervals = sorted(intervals, key=lambda interval: interval[0])
    merged: list[list[int]] = [list(sorted_intervals[0])]

    for start_year, end_year in sorted_intervals[1:]:
        last_merged = merged[-1]
        if start_year <= last_merged[1]:
            last_merged[1] = max(last_merged[1], end_year)
        else:
            merged.append([start_year, end_year])

    return float(sum(end_year - start_year for start_year, end_year in merged))


def analyze_work_experience(work_experience: list[dict]) -> dict:
    """
    نقطه‌ی ورود اصلی: لیست تجربیات شغلی (خروجی مرحله‌ی NER) را می‌گیرد، هر
    ردیف را اعتبارسنجی می‌کند، و مجموع سال‌های سابقه‌ی کاری خالص (فقط بر پایه‌ی
    دوره‌های معتبر، بعد از کسر تداخل‌های زمانی) را محاسبه می‌کند.

    خروجی شامل «entries» (همان ردیف‌های ورودی + start_year/end_year/is_valid/
    flag_reason برای هرکدام) و «total_experience_years» (عدد نهایی خالص) است.
    """
    analyzed_entries: list[dict] = []
    valid_intervals: list[tuple[int, int]] = []

    for entry in work_experience:
        duration = entry.get("duration")
        parsed = _parse_duration(duration)

        if parsed is None:
            analyzed_entries.append(
                {
                    **entry,
                    "start_year": None,
                    "end_year": None,
                    "is_valid": False,
                    "flag_reason": "بازه‌ی تاریخ در این ردیف قابل تشخیص نبود.",
                }
            )
            continue

        start_year, end_year = parsed
        is_shamsi = start_year < _SHAMSI_YEAR_THRESHOLD
        flag_reason = _validate_entry(start_year, end_year, is_shamsi)
        is_valid = flag_reason is None

        analyzed_entries.append(
            {
                **entry,
                "start_year": start_year,
                "end_year": end_year,
                "is_valid": is_valid,
                "flag_reason": flag_reason,
            }
        )

        if is_valid:
            valid_intervals.append((start_year, end_year))
        else:
            logger.info("یک ردیف تجربه‌ی شغلی فیلتر شد: %s", flag_reason)

    total_experience_years = _merge_intervals_and_sum_years(valid_intervals)

    return {
        "total_experience_years": total_experience_years,
        "entries": analyzed_entries,
    }
