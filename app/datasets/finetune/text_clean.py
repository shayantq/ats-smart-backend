"""
نرمال‌سازی و پاک‌سازی متن پیش از ورود به دیتاست.

سیاست ثابت (برای همه‌ی رکوردها یکسان):
- Unicode NFC؛ «ي/ى/ك» عربی → «ی/ک» فارسی؛ کشیده (ـ) حذف.
- همه‌ی ارقام فارسی/عربی → ارقام لاتین (0-9) تا اعداد در کل دیتاست یک شکل داشته باشند.
- نویسه‌های کنترلی، نویسه‌های قالب‌بندی نامرئی (Cf: zero-width، جهت‌نمای LRM/RLM، BOM) به‌جز
  نیم‌فاصله (ZWNJ, U+200C)، نویسه‌ی جایگزین U+FFFD، surrogate تنها و Private-Use حذف می‌شوند.
- mojibake (متن UTF-8 که اشتباهاً با Latin-1/CP1252 خوانده شده، مثل «Ø¹Ù„ÛŒ») تا جای ممکن تعمیر می‌شود؛
  اگر تعمیر نشد has_mojibake آن را گزارش می‌کند و رکورد کنار گذاشته می‌شود.
- فاصله‌های پشت‌سرهم یکی و بیش از یک خط خالی به یک خط خالی کاهش می‌یابد.
"""

from __future__ import annotations

import re
import unicodedata

ZWNJ = "\u200c"
REPLACEMENT_CHAR = "\ufffd"

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",  # ي → ی
        "ى": "ی",  # ى → ی
        "ك": "ک",  # ك → ک
        "ـ": None,  # کشیده
        "\t": " ",
        "\r": "\n",
        "\u00a0": " ",
        **{chr(0x06F0 + digit): str(digit) for digit in range(10)},
        **{chr(0x0660 + digit): str(digit) for digit in range(10)},
    }
)

# نویسه‌هایی که CP1252 در بازه‌ی 0x80-0x9F به جای کنترل‌های C1 نشان می‌دهد
_CP1252_SPECIALS = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
# متن UTF-8 که اشتباهاً به‌صورت Latin-1/CP1252 خوانده شده:
_CONTINUATION = f"[\u0080-\u00bf{_CP1252_SPECIALS}]"
# دنباله‌ی دوبایتی (0xC2-0xDF + ادامه، مثل حروف فارسی) یا سه‌بایتی (0xE0-0xEF + دو ادامه، مثل «—» و نیم‌فاصله)
_MOJIBAKE_PATTERN = re.compile(f"[\u00c2-\u00df]{_CONTINUATION}|[\u00e0-\u00ef]{_CONTINUATION}{{2}}")
_MOJIBAKE_RUN = re.compile(f"[\u00a0-\u00ff\u0080-\u009f{_CP1252_SPECIALS}]{{2,}}")

_HORIZONTAL_SPACE = re.compile(r"[ \u2000-\u200b\u202f\u205f\u3000]+")
_SPACE_AROUND_NEWLINE = re.compile(r" *\n *")
_EXTRA_NEWLINES = re.compile(r"\n{3,}")


def has_mojibake(text: str) -> bool:
    return bool(_MOJIBAKE_PATTERN.search(text))


def _repair_run(match: re.Match) -> str:
    run = match.group(0)
    if not has_mojibake(run):
        return run
    for codec in ("cp1252", "latin-1"):
        try:
            repaired = run.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if not has_mojibake(repaired):
            return repaired
    return run


def repair_mojibake(text: str) -> str:
    """تعمیر تکه‌به‌تکه: متن فارسی سالم کنار تکه‌ی خراب دست نمی‌خورد."""
    if not has_mojibake(text):
        return text
    return _MOJIBAKE_RUN.sub(_repair_run, text)


def _keep_char(char: str) -> bool:
    if char in ("\n", ZWNJ):
        return True
    if char == REPLACEMENT_CHAR:
        return False
    return unicodedata.category(char) not in ("Cc", "Cf", "Cs", "Co", "Cn")


def strip_invalid_chars(text: str) -> str:
    return "".join(char for char in text if _keep_char(char))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = repair_mojibake(text)
    text = unicodedata.normalize("NFC", text).translate(_CHAR_MAP)
    text = strip_invalid_chars(text)
    text = _HORIZONTAL_SPACE.sub(" ", text)
    text = _SPACE_AROUND_NEWLINE.sub("\n", text)
    text = _EXTRA_NEWLINES.sub("\n\n", text)
    return text.strip()


def fingerprint_text(text: str) -> str:
    """متن تهاجمی‌نرمال‌شده برای تشخیص رکوردهای تقریباً تکراری: فقط حروف، بدون ارقام/فاصله/علائم/حروف بزرگ."""
    return "".join(char for char in text.casefold() if char.isalpha())
