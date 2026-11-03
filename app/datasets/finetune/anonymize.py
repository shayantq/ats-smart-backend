"""
ناشناس‌سازی متن رکورد پیش از نوشتن روی دیسک (ورودی باید قبلاً با text_clean.normalize_text نرمال شده باشد؛
یعنی ارقام لاتین‌اند).

دو لایه:
۱. حذف مقدار دقیق شناسه‌های همین رکورد (نام و نام خانوادگی از پروفایل، خروجی پارسر و خط عنوان رزومه، بخش محلی
   ایمیل، تلفن، شهر) — نام‌ها با همان نرمال‌سازی متن رزومه یکسان می‌شوند و هر کلمه‌ی نام جدا (و شکل چسبیده‌ی
   نام چندکلمه‌ای، مثلاً «محمدرضا») جایگزین می‌شود.
۲. الگوهای عمومی: ایمیل؛ تلفن (هر دنباله‌ی رقمی با جداکننده‌ی دلخواه که بر اساس تعداد رقم و پیش‌شماره موبایل/ثابت
   ایران یا شماره‌ی بین‌المللی باشد، به‌علاوه‌ی هر عدد بعد از برچسب «تلفن/موبایل/phone»)؛ نشانی وب و دامنه‌ها و
   شناسه‌ی شبکه‌های اجتماعی؛ کد ملی ۱۰ رقمی؛ کد پستی؛ تاریخ تولد (فقط کنار برچسب «تولد/born/DOB» تا تاریخ‌های
   سوابق کاری حفظ شوند)؛ نشانی پستی (خط برچسب‌دار «آدرس/نشانی/محل سکونت/Address»).

مرز کلمه دقیقاً همان مرز ایندکس کور جستجو است (app/core/search_query.py)، تا اعتبارسنج (validate.py) با همان
توکن‌سازی و هش، باقی‌مانده‌ی احتمالی را ببیند.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.core.crypto import blind_index_token
from app.core.search_query import resume_search_words
from app.datasets.finetune.text_clean import normalize_text

NAME = "[NAME]"
EMAIL = "[EMAIL]"
PHONE = "[PHONE]"
LOCATION = "[LOCATION]"
ADDRESS = "[ADDRESS]"
URL = "[URL]"
NATIONAL_ID = "[NATIONAL_ID]"
POSTAL_CODE = "[POSTAL_CODE]"
BIRTH_DATE = "[BIRTH_DATE]"

MIN_NAME_TOKEN_LENGTH = 2
MIN_EMAIL_TOKEN_LENGTH = 3
MAX_HEADER_NAME_WORDS = 4
MAX_HEADER_NAME_CHARS = 40

ZWNJ = chr(0x200C)
_PHONE_SEPARATORS = r"\s\-./()" + ZWNJ
_EXACT_SEP = f"[{_PHONE_SEPARATORS}]*"
# دنباله‌ی ۸ تا ۱۶ رقمی با حداکثر دو نویسه‌ی جداکننده بین ارقام (« - » بین دو بازه‌ی سال مرز حساب می‌شود)
_DIGIT_RUN_RE = re.compile(rf"(?<![\d+])\(?\+?(?:\d[{_PHONE_SEPARATORS}]{{0,2}}){{7,15}}\d(?!\d)")
_PHONE_LABEL_RE = re.compile(
    rf"((?:تلفن|تماس|موبایل|همراه|شماره\s*تماس|phone|tel|mobile|cell)\s*[:：\-]?\s*)"
    rf"(\+?(?:\d[{_PHONE_SEPARATORS}]{{0,2}}){{6,14}}\d)(?!\d)",
    re.IGNORECASE,
)
_MOBILE_RE = re.compile(r"0?9\d{9}")
_LANDLINE_RE = re.compile(r"0[1-8]\d{9}")

_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_TLDS = "com|org|ir|io|me|dev|app|co|info|xyz|site|online|tech|ai|blog|page|ly|edu|gov|biz|us|uk|de|ca|tv"
_URL_RE = re.compile(
    r"(?:https?://|www\.)\S+"
    rf"|(?<![\w@.\-])(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+(?:{_TLDS})\b(?:/\S*)?"
    r"|(?<![\w@.\-])(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+net/\S+",
    re.IGNORECASE,
)
# نام فناوری‌هایی که شکل دامنه دارند و سیگنال مهارت‌اند، نه نشانی شخصی
TECH_DOTTED_NAMES = frozenset({"socket.io", "asp.net", "vb.net", "ado.net", "dot.net"})
_HANDLE_RE = re.compile(r"(?<![\w@.])@[A-Za-z0-9_.]{3,}")
_BIRTH_RE = re.compile(
    r"((?:تاریخ\s*تولد|سال\s*تولد|متولد|تولد|date\s*of\s*birth|birth\s*(?:date|day)|born(?:\s*(?:on|in))?|dob)"
    r"\s*[:：\-]?\s*(?:سال\s*)?)"
    r"(\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}|\d{1,2}\s+[^\W\d_]+\s+\d{2,4}|[^\W\d_]+\s+\d{1,2},?\s+\d{4}|\d{4})",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(r"((?:آدرس|نشانی|محل\s*سکونت|address)\s*[:：]\s*)([^\n|]+)", re.IGNORECASE)
_POSTAL_LABELED_RE = re.compile(r"((?:کد\s*پستی|postal\s*code|zip\s*code|zip)\s*[:：\-]?\s*)(\d{5}[\s\-]?\d{5})", re.I)
_NATIONAL_ID_RE = re.compile(r"(?<!\d)\d(?:[\s\-]?\d){9}(?!\d)")
_TOKEN_RE = re.compile(r"[^\W_]+")
_REPEATED_PLACEHOLDER_RE = re.compile(r"(\[[A-Z_]+\])(?:[\s,،]+\1)+")

# کلمه‌هایی که خط اول رزومه را «عنوان شغلی/سربرگ» نشان می‌دهند، نه نام شخص
_HEADER_STOPWORDS = frozenset(
    "resume cv curriculum vitae profile summary senior junior lead developer engineer backend frontend fullstack "
    "manager designer analyst specialist رزومه سوابق کاری خلاصه برنامه نویس توسعه دهنده کارشناس مهندس مدیر طراح "
    "تحلیلگر ارشد".split()
)


@dataclass(frozen=True)
class Identity:
    """شناسه‌های شناخته‌شده‌ی یک کارجو (رمزگشایی‌شده، فقط در حافظه)."""

    names: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()


def header_name(text: str) -> str | None:
    """خط اول رزومه اگر شبیه نام شخص باشد (۲ تا ۴ کلمه‌ی بدون رقم، کوتاه، نه عنوان شغلی/سربرگ)."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    words = _TOKEN_RE.findall(first_line)
    if not 2 <= len(words) <= MAX_HEADER_NAME_WORDS or len(first_line) > MAX_HEADER_NAME_CHARS:
        return None
    if any(char.isdigit() for char in first_line) or any(word.lower() in _HEADER_STOPWORDS for word in words):
        return None
    return first_line


def with_header_name(identity: Identity, resume_text: str) -> Identity:
    name = header_name(resume_text)
    return replace(identity, names=identity.names + (name,)) if name else identity


def _name_words(name: str) -> set[str]:
    words = resume_search_words(normalize_text(name))
    joined = {"".join(words)} if 2 <= len(words) <= 3 else set()
    return set(words) | joined


def name_tokens(identity: Identity) -> frozenset[str]:
    tokens = {word for name in identity.names for word in _name_words(name)}
    for email in identity.emails:
        local_part = normalize_text(email).split("@", 1)[0]
        tokens.update(word for word in resume_search_words(local_part) if len(word) >= MIN_EMAIL_TOKEN_LENGTH)
    return frozenset(token for token in tokens if len(token) >= MIN_NAME_TOKEN_LENGTH and not token.isdigit())


def _phone_digits(phone: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", normalize_text(phone))
    return digits[-10:] if len(digits) >= 8 else None


def identity_hashes(identity: Identity) -> list[str]:
    """هش HMAC (همان کلید ایندکس کور) توکن‌های شناسه — برای manifest؛ متن ساده هرگز ذخیره نمی‌شود."""
    values = set(name_tokens(identity))
    for phone in identity.phones:
        digits = _phone_digits(phone)
        if digits:
            values.update({digits, "0" + digits, "98" + digits})
    return sorted({blind_index_token(value) for value in values})


def _exact_phone_patterns(identity: Identity) -> list[re.Pattern]:
    patterns = []
    for phone in identity.phones:
        digits = _phone_digits(phone)
        if digits:
            body = _EXACT_SEP.join(re.escape(digit) for digit in digits)
            patterns.append(re.compile(rf"(?<!\d)(?:(?:\+|00)?98{_EXACT_SEP}|0{_EXACT_SEP})?{body}(?!\d)"))
    return patterns


def is_phone_number(raw: str) -> bool:
    digits = re.sub(r"[^0-9]", "", raw)
    # «00» فقط وقتی پیش‌شماره‌ی بین‌المللی است که شماره بلندتر از کد ملی ۱۰ رقمی باشد
    international = raw.lstrip("(").startswith("+") or (digits.startswith("00") and len(digits) >= 11)
    national = digits
    if digits.startswith("0098"):
        national = digits[4:]
    elif digits.startswith("98") and (international or len(digits) == 12):
        national = digits[2:]
    if _MOBILE_RE.fullmatch(national) or _LANDLINE_RE.fullmatch(national):
        return True
    if len(national) == 10 and national[0] in "12345678" and national != digits:
        return True  # +98 21 xxxx xxxx
    return international and 8 <= len(digits.lstrip("0")) <= 15


def _redact_phones(text: str) -> str:
    text = _PHONE_LABEL_RE.sub(lambda match: match.group(1) + PHONE, text)
    return _DIGIT_RUN_RE.sub(lambda match: PHONE if is_phone_number(match.group(0)) else match.group(0), text)


def _phrase_pattern(phrase: str) -> re.Pattern | None:
    words = _TOKEN_RE.findall(normalize_text(phrase))
    if not words:
        return None
    body = r"[\s,،\-]+".join(re.escape(word) for word in words)
    return re.compile(rf"(?<![^\W_]){body}(?![^\W_])", re.IGNORECASE)


def _redact_url(match: re.Match) -> str:
    return match.group(0) if match.group(0).lower() in TECH_DOTTED_NAMES else URL


def redact_patterns(text: str) -> str:
    """لایه‌ی الگوهای عمومی — برای متن آگهی هم اجرا می‌شود (ممکن است تلفن/ایمیل کارمند HR را داشته باشد)."""
    text = _EMAIL_RE.sub(EMAIL, text)
    text = _URL_RE.sub(_redact_url, text)
    text = _HANDLE_RE.sub(URL, text)
    text = _BIRTH_RE.sub(lambda match: match.group(1) + BIRTH_DATE, text)
    text = _POSTAL_LABELED_RE.sub(lambda match: match.group(1) + POSTAL_CODE, text)
    text = _redact_phones(text)
    text = _NATIONAL_ID_RE.sub(NATIONAL_ID, text)
    return _ADDRESS_RE.sub(lambda match: match.group(1) + ADDRESS, text)


def redact_names(text: str, tokens: frozenset[str]) -> str:
    if not tokens:
        return text
    redacted = _TOKEN_RE.sub(lambda match: NAME if match.group(0).lower() in tokens else match.group(0), text)
    return _REPEATED_PLACEHOLDER_RE.sub(r"\1", redacted)


def redact_locations(text: str, identity: Identity) -> str:
    for location in identity.locations:
        pattern = _phrase_pattern(location)
        if pattern is not None:
            text = pattern.sub(LOCATION, text)
    return text


@dataclass(frozen=True)
class Redactor:
    """ناشناس‌ساز یک رکورد؛ الگوهای دقیق یک بار ساخته و برای همه‌ی رشته‌های رکورد استفاده می‌شوند."""

    identity: Identity
    tokens: frozenset[str]
    phone_patterns: tuple[re.Pattern, ...]

    @classmethod
    def for_identity(cls, identity: Identity) -> "Redactor":
        return cls(identity, name_tokens(identity), tuple(_exact_phone_patterns(identity)))

    def _exact_phones(self, text: str) -> str:
        for pattern in self.phone_patterns:
            text = pattern.sub(PHONE, text)
        return text

    def resume_text(self, text: str) -> str:
        """متن رزومه: هر دو لایه + شهر کارجو."""
        text = self._exact_phones(text)
        text = redact_patterns(text)
        text = redact_locations(text, self.identity)
        return redact_names(text, self.tokens)

    def other_text(self, text: str) -> str:
        """آگهی و فیلدهای خروجی: الگوها + نام (شهر آگهی سیگنال شغلی است و حفظ می‌شود)."""
        return redact_names(redact_patterns(self._exact_phones(text)), self.tokens)
