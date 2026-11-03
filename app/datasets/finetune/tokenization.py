"""
شمارش توکن رکورد با توکنایزر مدل پایه‌ی هدف (فایل tokenizer.json؛ مسیرش با --tokenizer داده می‌شود و هیچ
مدل مشخصی در کد ثابت نشده است).

طول هر رکورد = طول کل گفت‌وگوی آموزشی در قالب چت ChatML (system=instruction، user=input، assistant=output)
به‌همراه نشانه‌های قالب — همان چیزی که هنگام آموزش در یک توالی قرار می‌گیرد.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from tokenizers import Tokenizer

DEFAULT_MAX_TOKENS = 4096


def render_chat(record: dict[str, str]) -> str:
    return (
        f"<|im_start|>system\n{record['instruction']}<|im_end|>\n"
        f"<|im_start|>user\n{record['input']}<|im_end|>\n"
        f"<|im_start|>assistant\n{record['output']}<|im_end|>\n"
    )


@lru_cache(maxsize=4)
def load_tokenizer(path: str) -> Tokenizer:
    return Tokenizer.from_file(str(Path(path)))


def tokenizer_fingerprint(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def count_tokens(tokenizer: Tokenizer, record: dict[str, str]) -> int:
    return len(tokenizer.encode(render_chat(record), add_special_tokens=False).ids)


def round_trips(tokenizer: Tokenizer, text: str) -> bool:
    """متن پس از encode → decode بدون تغییر برگردد (هیچ بایت/نویسه‌ای به توکن ناشناخته تبدیل نشده باشد)."""
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    return tokenizer.decode(ids, skip_special_tokens=False) == text
