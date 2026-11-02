"""
سیگنال‌های متنی مشترک بین عامل‌ها: ادعای «سال سابقه» در متن رزومه (کل، یا برای یک مهارت خاص).

این ادعاها با سابقه‌ی واقعی محاسبه‌شده از بازه‌های تاریخ مقایسه می‌شوند (عامل اعتبارسنجی سوابق و عامل
ناظر) — اختلاف زیاد نشانه‌ی بزرگ‌نمایی است. evidence فقط یک تکه‌ی کوتاه از متن برای نمایش به HR است و هرگز
لاگ نمی‌شود.
"""

import re

from app.core.skill_graph import match_skills

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MAX_EVIDENCE_LENGTH = 80
_MAX_PLAUSIBLE_YEARS = 50

_YEARS = r"(\d{1,2})\s*\+?\s*"
_TOTAL_CLAIM_PATTERNS = [
    re.compile(
        _YEARS + r"(?:years?|yrs)\s+(?:of\s+)?(?:professional\s+|industry\s+|work\s+|hands-on\s+)?experience", re.I
    ),
    re.compile(r"experience\s+of\s+" + _YEARS + r"(?:years?|yrs)", re.I),
    re.compile(_YEARS + r"سال\s+(?:سابقه|تجربه)"),
    re.compile(r"(?:سابقه|تجربه)(?:\s+کاری|\s+کار)?\s+" + _YEARS + r"سال"),
]
# «۸ سال Python»، «8 years of Kubernetes»، «5+ years experience with React»
_SKILL_CLAIM_AFTER = re.compile(
    _YEARS
    + r"(?:years?|yrs|سال)\s+(?:of\s+)?(?:experience\s+(?:in|with)\s+|تجربه\s+|سابقه\s+)?(?:در\s+|با\s+|کار\s+با\s+)?"
    # پنجره‌ی نام مهارت در lookahead: مصرف نمی‌شود تا ادعای بعدی («… و ۲ سال React») هم پیدا شود
    r"(?=([^,;()\n،؛]{1,40}))",
    re.I,
)
# پنجره‌ی بعد از «N سال» در «و/and» هم قطع می‌شود تا ادعای یک مهارت به مهارت بعدی نرسد
_WINDOW_SPLIT = re.compile(r"\s(?:and|و|&)\s|/", re.I)
# «Python (8 years)»، «Django - 4 yrs»، «Docker: ۳ سال»
_SKILL_CLAIM_BEFORE = re.compile(r"([A-Za-z][\w.#+/\- ]{0,30}?)\s*[\(\-–:]\s*" + _YEARS + r"(?:years?|yrs|سال)", re.I)


def compute_shared_signals(text: str | None) -> dict:
    """
    سیگنال‌هایی که بیش از یک عامل لازم دارند — عامل ناظر یک‌بار در توزیع حساب و به همه می‌دهد (نه هر عامل جدا):
    {"claimed_total": (سال، evidence)، "skill_year_claims": {مهارت: (سال، evidence)}}
    """
    return {"claimed_total": extract_claimed_total_years(text), "skill_year_claims": extract_skill_year_claims(text)}


def normalize_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS)


def _evidence(text: str, match: re.Match, extra: int = 0) -> str:
    return " ".join(text[match.start() : match.end() + extra].split())[:_MAX_EVIDENCE_LENGTH]


def extract_claimed_total_years(text: str | None) -> tuple[float | None, str | None]:
    """بیشترین «N سال سابقه»ی ادعاشده در کل متن؛ (None, None) اگر ادعایی نیست."""
    if not text:
        return None, None
    normalized = normalize_digits(text)
    best: tuple[float | None, str | None] = (None, None)
    for pattern in _TOTAL_CLAIM_PATTERNS:
        for match in pattern.finditer(normalized):
            years = float(match.group(1))
            if 0 < years <= _MAX_PLAUSIBLE_YEARS and (best[0] is None or years > best[0]):
                best = (years, _evidence(normalized, match))
    return best


def extract_skill_year_claims(text: str | None) -> dict[str, tuple[float, str]]:
    """
    {نام استاندارد مهارت: (سال ادعاشده، evidence)} — اگر یک مهارت چند ادعا دارد، بیشترین. مهارت با همان
    گراف مهارت تشخیص داده می‌شود؛ والدِ مهارت (Python برای Django) ادعا را به ارث نمی‌برد.
    """
    if not text:
        return {}
    normalized = normalize_digits(text)
    claims: dict[str, tuple[float, str]] = {}

    def record(years: float, window: str, evidence: str) -> None:
        if not 0 < years <= _MAX_PLAUSIBLE_YEARS:
            return
        found = match_skills(window)
        # فقط مهارت‌هایی که خودشان در پنجره آمده‌اند (match_skills والد را هم اضافه می‌کند)
        direct = [skill for skill in found if re.search(re.escape(skill), window, re.I)]
        for skill in direct:
            if skill not in claims or years > claims[skill][0]:
                claims[skill] = (years, evidence)

    for match in _SKILL_CLAIM_AFTER.finditer(normalized):
        window = _WINDOW_SPLIT.split(match.group(2))[0]
        record(float(match.group(1)), window, _evidence(normalized, match, len(window)))
    for match in _SKILL_CLAIM_BEFORE.finditer(normalized):
        record(float(match.group(2)), match.group(1), _evidence(normalized, match))
    return claims
