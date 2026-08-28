"""
ماژول پارسینگ متنی و بازشناسی موجودیت‌های نامدار (NER) برای رزومه.

مرحله‌ی دوم خط لوله‌ی هوش مصنوعی: متن خام بدون‌ساختار (raw_text، خروجی مرحله‌ی
OCR در app/core/text_extraction.py) را می‌گیرد و آن را به یک شیء JSON
ساختاریافته (اطلاعات فردی + سوابق تحصیلی + تجربیات شغلی) تبدیل می‌کند.

رویکرد ترکیبی (Hybrid) — عمداً انتخاب شده چون دقیق‌تر از یک مدل NER تنها است:
- موجودیت‌های با الگوی ثابت و قابل‌پیش‌بینی (ایمیل، تلفن، معدل، بازه‌ی تاریخ)
  با عبارت‌های باقاعده (Regex) استخراج می‌شوند.
- موجودیت‌های آزاد بدون الگوی ثابت (نام شخص، نام شرکت/دانشگاه) در کنار قواعد
  متنی، با مدل NER کتابخانه‌ی spaCy (در صورت نصب/موجود بودن مدل زبانی) کمک
  می‌گیرند تا مرزبندی دقیق‌تری داشته باشند.

محدودیت شناخته‌شده: مدل NER استفاده‌شده (en_core_web_sm) برای زبان انگلیسی
آموزش دیده و برای بخش‌های فارسی متن صرفاً کمکی/جانبی عمل می‌کند؛ استخراج
فارسی عمدتاً روی قواعد متنی (Regex + کلیدواژه) تکیه دارد. جزئیات این
محدودیت در README مستند شده است.
"""

import logging
import re

from app.schemas.resume_parsing import EducationEntry, ParsedResumeData, PersonalInfo, WorkExperienceEntry

logger = logging.getLogger("ats_smart.resume_parser")

# --------------------------------------------------------------------------
# نرمال‌سازی ارقام فارسی/عربی به لاتین، تا تمام Regex های زیر با یک فرمت یکسان کار کنند
# --------------------------------------------------------------------------
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_TRANSLATION_TABLE = {
    **{ord(ch): str(i) for i, ch in enumerate(_PERSIAN_DIGITS)},
    **{ord(ch): str(i) for i, ch in enumerate(_ARABIC_DIGITS)},
}


def _normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_TRANSLATION_TABLE)


# --------------------------------------------------------------------------
# عبارت‌های باقاعده برای موجودیت‌های با الگوی ثابت
# --------------------------------------------------------------------------
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_PATTERN = re.compile(r"(?:\+98|0)?9\d{9}\b")
_GPA_PATTERN = re.compile(r"(?:معدل|GPA)\s*[:ـ]?\s*([0-9]+(?:[.,][0-9]+)?)", re.IGNORECASE)
_DATE_RANGE_PATTERN = re.compile(
    r"((?:1[349]\d{2}|20\d{2}))\s*(?:[-–—]+|تا|to)\s*"
    r"((?:1[349]\d{2}|20\d{2}|تاکنون|اکنون|حال حاضر|present|current))",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# هدینگ‌های متداول بخش‌های رزومه (فارسی + انگلیسی) برای مرزبندی بخش‌ها
# --------------------------------------------------------------------------
_EXPERIENCE_SECTION_HEADERS = (
    "تجربه کاری",
    "تجربیات شغلی",
    "سوابق شغلی",
    "سوابق کاری",
    "سابقه کار",
    "work experience",
    "employment history",
    "professional experience",
    "experience",
)
_EDUCATION_SECTION_HEADERS = (
    "سوابق تحصیلی",
    "تحصیلات دانشگاهی",
    "تحصیلات",
    "education",
    "academic background",
    "academic qualifications",
)
_MAX_SECTION_HEADER_LINE_LENGTH = 40  # فقط خط‌های کوتاه/تیتروار به‌عنوان مرز بخش پذیرفته می‌شوند

_JOB_TITLE_KEYWORDS = (
    "توسعه‌دهنده",
    "برنامه‌نویس",
    "مهندس",
    "کارشناس",
    "مدیر",
    "طراح",
    "تحلیلگر",
    "developer",
    "engineer",
    "manager",
    "designer",
    "analyst",
    "specialist",
    "consultant",
    "administrator",
    "lead",
    "architect",
)
_DEGREE_KEYWORDS = (
    "دکتری",
    "کارشناسی ارشد",
    "کارشناسی",
    "کاردانی",
    "دیپلم",
    "phd",
    "ph.d",
    "master",
    "bachelor",
    "associate",
    "mba",
    "b.sc",
    "m.sc",
)

_ORG_KEYWORD_PATTERN = re.compile(r"(?:شرکت|سازمان)\s+([^\n,،.]{2,60})")
_UNIVERSITY_KEYWORD_PATTERN = re.compile(r"دانشگاه\s+([^\n,،.]{2,60})")


# --------------------------------------------------------------------------
# بارگذاری تنبل (Lazy Load) مدل spaCy — اگر نصب/دانلود نشده باشد، ماژول
# بدون کرش کردن، فقط با تکیه بر قواعد متنی ادامه می‌دهد (مثل الگوی
# lazy import در app/core/storage.py برای boto3).
# --------------------------------------------------------------------------
_spacy_model = None
_spacy_load_attempted = False


def _get_spacy_model():
    global _spacy_model, _spacy_load_attempted
    if _spacy_load_attempted:
        return _spacy_model

    _spacy_load_attempted = True
    try:
        import spacy

        _spacy_model = spacy.load("en_core_web_sm")
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "مدل NER کتابخانه‌ی spaCy در دسترس نیست؛ استخراج نام/سازمان فقط بر پایه‌ی "
            "قواعد متنی انجام می‌شود (دقت کمتر برای نام‌های آزاد). خطا: %s",
            error,
        )
        _spacy_model = None

    return _spacy_model


def parse_resume_text(raw_text: str) -> ParsedResumeData:
    """
    نقطه‌ی ورود اصلی ماژول: متن خام (raw_text) را می‌گیرد و شیء ساختاریافته‌ی
    نهایی (اطلاعات فردی + سوابق تحصیلی + تجربیات شغلی) را برمی‌گرداند تا به
    مرحله‌ی بعدی خط لوله (امتیازدهی هوش مصنوعی) منتقل شود.
    """
    normalized_text = _normalize_digits(raw_text)
    sections = _split_into_sections(normalized_text)

    personal_info = _extract_personal_info(sections["header"], normalized_text)
    work_experience = _extract_work_experience(sections["experience"])
    education = _extract_education(sections["education"])

    return ParsedResumeData(
        personal_info=personal_info,
        education=education,
        work_experience=work_experience,
    )


def _split_into_sections(text: str) -> dict[str, str]:
    """
    متن را بر اساس هدینگ‌های شناخته‌شده به سه بخش می‌شکند: header (هرچه پیش از
    اولین هدینگ شناخته‌شده، معمولاً شامل اطلاعات فردی)، experience، و education.
    """
    lines = text.splitlines()
    sections: dict[str, list[str]] = {"header": [], "experience": [], "education": []}
    current_section = "header"

    for line in lines:
        normalized_line = line.strip().lower()
        is_short_line = len(normalized_line) < _MAX_SECTION_HEADER_LINE_LENGTH

        if is_short_line and any(header in normalized_line for header in _EXPERIENCE_SECTION_HEADERS):
            current_section = "experience"
            continue

        if is_short_line and any(header in normalized_line for header in _EDUCATION_SECTION_HEADERS):
            current_section = "education"
            continue

        sections[current_section].append(line)

    return {name: "\n".join(section_lines) for name, section_lines in sections.items()}


def _split_into_blocks(section_text: str) -> list[str]:
    """یک بخش را بر اساس خط‌های خالی به قطعات مجزا (هر قطعه معادل یک ردیف تجربه/تحصیل) می‌شکند."""
    raw_blocks = re.split(r"\n\s*\n", section_text.strip())
    return [block.strip() for block in raw_blocks if block.strip()]


def _extract_personal_info(header_text: str, full_text: str) -> PersonalInfo:
    email_match = _EMAIL_PATTERN.search(full_text)
    phone_match = _PHONE_PATTERN.search(full_text)

    return PersonalInfo(
        name=_guess_name(header_text),
        email=email_match.group(0) if email_match else None,
        phone=phone_match.group(0) if phone_match else None,
    )


def _guess_name(header_text: str) -> str | None:
    nlp = _get_spacy_model()
    if nlp is not None:
        document = nlp(header_text[:500])
        person_entities = [entity.text.strip() for entity in document.ents if entity.label_ == "PERSON"]
        if person_entities:
            return person_entities[0]

    # جایگزین بدون spaCy: طبق قرارداد رایج رزومه‌ها، نام معمولاً اولین خط غیرخالی سند است
    # (به شرطی که خودِ آن خط ایمیل یا شماره تلفن نباشد)
    for line in header_text.splitlines():
        stripped_line = line.strip()
        if stripped_line and not _EMAIL_PATTERN.search(stripped_line) and not _PHONE_PATTERN.search(stripped_line):
            return stripped_line

    return None


def _extract_work_experience(section_text: str) -> list[WorkExperienceEntry]:
    if not section_text.strip():
        return []

    nlp = _get_spacy_model()
    entries: list[WorkExperienceEntry] = []

    for block in _split_into_blocks(section_text):
        duration = _find_duration(block)
        company = _find_organization(block, nlp, _ORG_KEYWORD_PATTERN)
        job_title = _find_keyword_line(block, _JOB_TITLE_KEYWORDS)

        if duration or company or job_title:
            entries.append(WorkExperienceEntry(company=company, job_title=job_title, duration=duration))

    return entries


def _extract_education(section_text: str) -> list[EducationEntry]:
    if not section_text.strip():
        return []

    nlp = _get_spacy_model()
    entries: list[EducationEntry] = []

    for block in _split_into_blocks(section_text):
        degree = _find_degree(block)
        university = _find_organization(block, nlp, _UNIVERSITY_KEYWORD_PATTERN)
        gpa = _find_gpa(block)

        if degree or university or gpa is not None:
            entries.append(EducationEntry(degree=degree, university=university, gpa=gpa))

    return entries


def _find_duration(block: str) -> str | None:
    match = _DATE_RANGE_PATTERN.search(block)
    if match:
        return f"{match.group(1)} - {match.group(2)}"
    return None


def _find_organization(block: str, nlp, keyword_pattern: re.Pattern[str]) -> str | None:
    """
    اول قاعده‌ی متنی فارسی («شرکت X» / «دانشگاه X») را امتحان می‌کند؛ اگر چیزی
    پیدا نشد و مدل spaCy در دسترس بود، به موجودیت‌های ORG آن (عمدتاً برای
    بخش‌های انگلیسی متن) رجوع می‌کند.
    """
    keyword_match = keyword_pattern.search(block)
    if keyword_match:
        return keyword_match.group(1).strip()

    if nlp is not None:
        document = nlp(block)
        org_entities = [entity.text.strip() for entity in document.ents if entity.label_ == "ORG"]
        if org_entities:
            return org_entities[0]

    return None


def _find_keyword_line(block: str, keywords: tuple[str, ...]) -> str | None:
    for line in block.splitlines():
        lowered_line = line.lower()
        if any(keyword in lowered_line for keyword in keywords):
            return line.strip()
    return None


def _find_degree(block: str) -> str | None:
    lowered_block = block.lower()
    for keyword in _DEGREE_KEYWORDS:
        if keyword in lowered_block:
            return keyword
    return None


def _find_gpa(block: str) -> float | None:
    match = _GPA_PATTERN.search(block)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None
