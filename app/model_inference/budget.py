import hashlib
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock

_SPECIAL = re.compile(r"<\|[^<>\s]+\|>|</?tool_call>")
_TEXT_PIECES = re.compile(r"[^\W\d_]+|\d")
_logger = logging.getLogger(__name__)
_warning_lock = Lock()
_warned_pid: int | None = None


@dataclass(frozen=True)
class PromptBudget:
    prompt_tokens: int
    output_reserved: int
    context_limit: int
    method: str
    tokenizer_sha256: str | None = None
    exact_count_failed: bool = False

    @property
    def over_by(self) -> int:
        return max(0, self.prompt_tokens + self.output_reserved - self.context_limit)

    def metrics(self) -> dict:
        result = {
            "prompt_tokens": self.prompt_tokens,
            "output_reserved": self.output_reserved,
            "context_limit": self.context_limit,
            "over_by": self.over_by,
            "method": self.method,
        }
        if self.tokenizer_sha256 is not None:
            result["tokenizer_sha256"] = self.tokenizer_sha256
        if self.exact_count_failed:
            result["exact_count_failed"] = 1
        return result


@lru_cache(maxsize=1)
def _load_tokenizer(path: str):
    data = Path(path).read_bytes()
    from tokenizers import Tokenizer

    return Tokenizer.from_buffer(data), hashlib.sha256(data).hexdigest()


def _warn_exact_failure(error: Exception) -> None:
    global _warned_pid
    pid = os.getpid()
    with _warning_lock:
        if _warned_pid == pid:
            return
        _warned_pid = pid
    _logger.warning(type(error).__name__)


def configured_tokenizer_sha256(path: str) -> str | None:
    if path:
        try:
            return _load_tokenizer(path)[1]
        except Exception as error:
            _warn_exact_failure(error)
    return None


def _estimate(prompt: str) -> int:
    normalized = unicodedata.normalize("NFC", prompt)
    arabic = sum("ARABIC" in unicodedata.name(char, "") and char.isalpha() for char in normalized)
    ratio = (45 * arabic + 20 * (len(normalized) - arabic)) // 100
    # توکنایزر فعلی Qwen برای هر بخش حرفی یا رقم جدا حداقل یک توکن دارد.
    # نشانه‌های ویژه ممکن است چند بخش را در یک توکن ادغام کنند.
    pieces = sum(1 for _ in _TEXT_PIECES.finditer(_SPECIAL.sub(" ", normalized)))
    return min(ratio, pieces)


def check_prompt_budget(prompt: str, context_limit: int, output_limit: int, tokenizer_file: str = "") -> PromptBudget:
    exact_failed = False
    if tokenizer_file:
        try:
            tokenizer, digest = _load_tokenizer(tokenizer_file)
            token_count = len(tokenizer.encode(prompt, add_special_tokens=False).ids)
            return PromptBudget(token_count, output_limit, context_limit, "exact", digest)
        except Exception as error:
            exact_failed = True
            _warn_exact_failure(error)
    return PromptBudget(_estimate(prompt), output_limit, context_limit, "estimate", exact_count_failed=exact_failed)
