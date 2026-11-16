"""سوابق مستند؛ پیش‌بینی مدل هرگز شاهد استخدام محسوب نمی‌شود."""

import re
import unicodedata
from datetime import date


VERSION = 2
MONTHS = "فروردین اردیبهشت خرداد تیر مرداد شهریور مهر آبان آذر دی بهمن اسفند".split()
HEADS = {"سوابق کاری", "سوابق شغلی", "تجربه کاری", "work experience", "employment history", "experience"}
STOPS = {
    "پروژه‌ها",
    "پروژه ها",
    "پروژه",
    "projects",
    "تحصیلات",
    "education",
    "مهارت‌ها",
    "مهارت ها",
    "skills",
    "زبان‌ها",
    "زبان ها",
}
ROLE = re.compile(
    r"کارآموز|توسعه.?دهنده|توسعه|برنامه.?نویس|کارشناس|مهندس|مدیر|intern|developer|engineer|manager|analyst", re.I
)
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك", "01234567890123456789یک")


def normalize(text):
    return " ".join(
        unicodedata.normalize("NFKC", text)
        .translate(DIGITS)
        .replace("\u200c", " ")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .split()
    ).lower()


def extract_employment(text, *, layout=None, reference=None):
    from app.core.structured_resume import legacy_work

    return legacy_work(text, layout, reference)


def endpoint(text, reference):
    from app.core.resume_dates import endpoint as parse_endpoint

    return parse_endpoint(text, reference)


def analyze_evidence(entries, reference=None):
    from app.core.resume_dates import date_range, union_years

    reference = reference or date.today()
    result, intervals = [], []
    for entry in entries:
        parsed = date_range(entry.get("duration"), reference)
        record = dict(
            entry,
            is_valid=parsed["status"] == "valid",
            start_year=None,
            end_year=None,
            flag_reason="date_unknown_or_invalid",
        )
        if parsed["status"] == "valid":
            record.update(start_year=parsed["start"]["year"], end_year=parsed["end"]["year"], flag_reason=None)
            intervals.append(
                (date.fromisoformat(parsed["start"]["latest"]), date.fromisoformat(parsed["end"]["earliest"]))
            )
        result.append(record)
    return result, union_years(intervals)
