"""
بررسی‌های اعتبارسنج دیتاست — عمداً مستقل از کد ساخت (anonymize/text_clean/cleanse را import نمی‌کند) تا اشکال
احتمالی همان کد، در اعتبارسنجی هم پنهان نماند. فقط تابع هش HMAC (app/core/crypto) و توکن‌سازی کلمه‌ی
ایندکس کور (app/core/search_query) مشترک‌اند، چون manifest با همان‌ها ساخته شده است.

هر بررسی فهرستی از کد خطا برمی‌گرداند؛ محتوای رکورد هرگز در گزارش نمی‌آید.
"""

from __future__ import annotations

import json
import re
import unicodedata

from app.core.crypto import blind_index_token
from app.core.search_query import resume_search_words

REQUIRED_KEYS = ("instruction", "input", "output")
ALLOWED_INVISIBLE = {"\u200c"}  # نیم‌فاصله‌ی فارسی

_SEPARATORS = r"[ \t\-./()" + chr(0x200C) + "]"
_TLD = "com|org|ir|io|me|dev|app|co|info|xyz|site|online|tech|ai|blog|page|ly|edu|gov|biz|us|uk|de|ca|tv"
_TECH_NAMES = {"socket.io", "asp.net", "vb.net", "ado.net", "dot.net"}
_PII_PATTERNS = {
    "pii_email": re.compile(r"[^\s@\[\]]+@[^\s@\[\]]+\.[A-Za-z]{2,}"),
    "pii_handle": re.compile(r"(?<![\w@.])@[A-Za-z0-9_]{3,}"),
    "pii_national_id": re.compile(r"(?<!\d)\d(?:[\s\-]?\d){9}(?!\d)"),
    "pii_birth_date": re.compile(r"(?:تولد|born|birth|dob)[^\n\d\[]{0,12}\d", re.IGNORECASE),
    "pii_address": re.compile(r"(?:آدرس|نشانی|محل\s*سکونت|address)\s*[:：]\s*(?!\[ADDRESS\])\S", re.IGNORECASE),
}
_URL_START = re.compile(r"https?://|www\.", re.IGNORECASE)
_DOMAIN = re.compile(rf"(?<![\w@.\-])[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:(?:{_TLD})\b|net/)", re.IGNORECASE)
_DIGITS = re.compile(rf"\+?\(?\d(?:{_SEPARATORS}{{0,2}}\d){{7,15}}")
_PHONE_AFTER_LABEL = re.compile(r"(?:تلفن|تماس|موبایل|همراه|phone|tel|mobile|cell)\s*[:：\-]?\s*\+?\d", re.I)
_IRAN_PHONE = re.compile(r"(?:0098|98|0)?9\d{9}|(?:0098|98|0)[1-8]\d{9}")


def _looks_like_phone(raw: str) -> bool:
    digits = "".join(char for char in raw if char.isdigit())
    if _IRAN_PHONE.fullmatch(digits):
        return True
    return raw.startswith(("+", "(+")) and 9 <= len(digits) <= 15 or digits.startswith("00") and 11 <= len(digits) <= 17


def _has_url(value: str) -> bool:
    if _URL_START.search(value):
        return True
    return any(match.group(0).rstrip("/").lower() not in _TECH_NAMES for match in _DOMAIN.finditer(value))


def _has_phone(value: str) -> bool:
    if _PHONE_AFTER_LABEL.search(value):
        return True
    for match in _DIGITS.finditer(value):
        start, end = match.span()
        boundary_ok = (start == 0 or not value[start - 1].isdigit()) and (end == len(value) or not value[end].isdigit())
        if boundary_ok and _looks_like_phone(match.group(0)):
            return True
    return False


_CP1252 = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
_TAIL = f"[\u0080-\u00bf{_CP1252}]"
_MOJIBAKE = re.compile(f"[\u00c2-\u00df]{_TAIL}|[\u00e0-\u00ef]{_TAIL}{_TAIL}")


def check_schema(raw: bytes) -> tuple[dict | None, list[str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, ["schema_invalid_utf8"]
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        return None, ["schema_invalid_json"]
    if not isinstance(record, dict) or tuple(sorted(record)) != tuple(sorted(REQUIRED_KEYS)):
        return None, ["schema_keys"]
    if not all(isinstance(record[key], str) and record[key].strip() for key in REQUIRED_KEYS):
        return None, ["schema_empty_field"]
    return record, _check_output(record["output"])


def _check_output(output: str) -> list[str]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return ["schema_output_json"]
    score = payload.get("score") if isinstance(payload, dict) else None
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        return ["schema_score_range"]
    return []


def check_pii(record: dict, pii_hashes: set[str]) -> list[str]:
    issues = []
    for value in record.values():
        issues += [code for code, pattern in _PII_PATTERNS.items() if pattern.search(value)]
        issues += ["pii_phone"] if _has_phone(value) else []
        issues += ["pii_url"] if _has_url(value) else []
        if pii_hashes and any(blind_index_token(word) in pii_hashes for word in set(resume_search_words(value))):
            issues.append("pii_identity")
    return sorted(set(issues))


def _char_issue(char: str) -> str | None:
    if char == "\ufffd":
        return "broken_replacement_char"
    if "\ud800" <= char <= "\udfff":
        return "broken_surrogate"
    category = unicodedata.category(char)
    if category == "Cc" and char != "\n":
        return "broken_control_char"
    if category in ("Cf", "Co", "Cn") and char not in ALLOWED_INVISIBLE:
        return "broken_invisible_char"
    return None


def check_broken(record: dict, tokenizer) -> list[str]:
    issues = set()
    for value in record.values():
        issues.update(issue for issue in map(_char_issue, value) if issue)
        if _MOJIBAKE.search(value):
            issues.add("broken_mojibake")
        if "broken_surrogate" in issues:
            continue  # توکنایزر surrogate تنها را نمی‌پذیرد
        ids = tokenizer.encode(value, add_special_tokens=False).ids
        if tokenizer.decode(ids, skip_special_tokens=False) != value:
            issues.add("broken_round_trip")
    return sorted(issues)


def conversation_tokens(record: dict, tokenizer) -> int:
    """طول گفت‌وگوی آموزشی کامل (قالب ChatML) — مستقل از tokenization.py ساخته می‌شود."""
    parts = (("system", "instruction"), ("user", "input"), ("assistant", "output"))
    text = "".join(f"<|im_start|>{role}\n{record[key]}<|im_end|>\n" for role, key in parts)
    return len(tokenizer.encode(text, add_special_tokens=False).ids)


def check_splits(groups: dict[str, set[str]], counts: dict[str, int], targets: dict[str, float], tolerance: float):
    issues = []
    names = list(groups)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            if groups[first] & groups[second]:
                issues.append(f"leakage_group:{first}/{second}")
    total = sum(counts.values())
    for name, target in targets.items():
        ratio = counts.get(name, 0) / total if total else 0.0
        if abs(ratio - target) > tolerance:
            issues.append(f"split_ratio:{name}")
    return issues
