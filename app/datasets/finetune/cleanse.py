"""
پاک‌سازی داده (Data Cleansing): هر جفت خام از این قوانین به ترتیب می‌گذرد و اولین قانونی که ردش کند در
شمارنده‌ی همان قانون ثبت می‌شود (گزارش stats.json). خروجی برای جفت قبول‌شده یک CleanRecord است.

قوانین (نام شمارنده ← شرط رد):
  ambiguous_resume_link      رزومه‌ی متناظر این درخواست قابل تشخیص نیست
  incomplete_resume_text     متن رزومه خالی
  incomplete_job             عنوان و شرح آگهی هر دو خالی
  missing_score              score_ai ندارد
  missing_agent_analysis     خروجی اکوسیستم چندعاملی ندارد یا کاملاً ناموفق بوده
  outlier_score              نمره خارج از 0 تا 100
  outlier_experience_years   سابقه‌ی کاری منفی یا بیش از سقف (پیش‌فرض ۵۰ سال)
  mojibake                   متن خراب (کدگذاری اشتباه) که تعمیرپذیر نبود
  outlier_resume_too_short   متن رزومه‌ی نرمال‌شده کوتاه‌تر از حد پایین
  outlier_resume_too_long    متن رزومه‌ی نرمال‌شده بلندتر از حد بالا
  duplicate_exact            input دقیقاً تکراری
  duplicate_near             input تقریباً تکراری (فقط حروف، بدون ارقام/فاصله/علائم/حروف بزرگ)
  pii_residual               پس از ناشناس‌سازی هنوز شناسه یا الگوی هویتی در رکورد مانده (خودآزمایی)
  tokenizer_round_trip       رکورد پس از encode/decode توکنایزر عیناً برنمی‌گردد
  too_many_tokens            طول گفت‌وگو بیش از --max-tokens
  invalid_record             مقدار نامعتبر در داده‌ی خام (مثلاً نمره‌ی غیرعددی در agent_analysis) — فقط شمرده می‌شود
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

from app.core.crypto import blind_index_token
from app.core.search_query import resume_search_words
from app.datasets.finetune.anonymize import Redactor, identity_hashes, redact_patterns, with_header_name
from app.datasets.finetune.records import PairSource, build_record
from app.datasets.finetune.text_clean import fingerprint_text, has_mojibake, normalize_text
from app.datasets.finetune.tokenization import DEFAULT_MAX_TOKENS, count_tokens, round_trips

SCORE_BUCKET_WIDTH = 20
SCORE_BUCKETS = 5

RULES = (
    "ambiguous_resume_link",
    "incomplete_resume_text",
    "incomplete_job",
    "missing_score",
    "missing_agent_analysis",
    "outlier_score",
    "outlier_experience_years",
    "mojibake",
    "outlier_resume_too_short",
    "outlier_resume_too_long",
    "duplicate_exact",
    "duplicate_near",
    "pii_residual",
    "tokenizer_round_trip",
    "too_many_tokens",
    "invalid_record",
)


@dataclass(frozen=True)
class CleansingConfig:
    min_resume_chars: int = 200
    max_resume_chars: int = 15000
    max_experience_years: float = 50.0
    max_tokens: int = DEFAULT_MAX_TOKENS


@dataclass(frozen=True)
class CleanRecord:
    record: dict[str, str]
    group: str
    bucket: int
    pii_hashes: list[str]
    tokens: int


def score_bucket(score: int) -> int:
    return min(score // SCORE_BUCKET_WIDTH, SCORE_BUCKETS - 1)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_rejection(source: PairSource, config: CleansingConfig) -> str | None:
    if source.ambiguous_link:
        return "ambiguous_resume_link"
    if not (source.resume_text or "").strip():
        return "incomplete_resume_text"
    if not (source.job.title or "").strip() and not (source.job.description or "").strip():
        return "incomplete_job"
    if source.score_ai is None:
        return "missing_score"
    if not source.analysis or source.analysis.get("status") == "failed":
        return "missing_agent_analysis"
    if not 0 <= source.score_ai <= 100:
        return "outlier_score"
    years = float(((source.analysis.get("experience") or {}).get("total_experience_years")) or 0.0)
    if not 0 <= years <= config.max_experience_years:
        return "outlier_experience_years"
    return None


def _text_rejection(text: str, config: CleansingConfig) -> str | None:
    if has_mojibake(text):
        return "mojibake"
    if len(text) < config.min_resume_chars:
        return "outlier_resume_too_short"
    if len(text) > config.max_resume_chars:
        return "outlier_resume_too_long"
    return None


def has_pii_residual(record: dict[str, str], pii_hashes: set[str]) -> bool:
    for value in record.values():
        if redact_patterns(value) != value:
            return True
        if pii_hashes and any(blind_index_token(word) in pii_hashes for word in set(resume_search_words(value))):
            return True
    return False


@dataclass
class Cleanser:
    tokenizer: object
    config: CleansingConfig = field(default_factory=CleansingConfig)
    counters: Counter = field(default_factory=Counter)
    _seen_exact: set[str] = field(default_factory=set)
    _seen_near: set[str] = field(default_factory=set)

    def _reject(self, rule: str) -> None:
        self.counters[rule] += 1

    def _is_duplicate(self, record: dict[str, str]) -> bool:
        exact, near = _sha(record["input"]), _sha(fingerprint_text(record["input"]))
        if exact in self._seen_exact:
            self._reject("duplicate_exact")
            return True
        if near in self._seen_near:
            self._reject("duplicate_near")
            return True
        self._seen_exact.add(exact)
        self._seen_near.add(near)
        return False

    def _final_rejection(self, record: dict[str, str], pii_hashes: list[str]) -> tuple[str | None, int]:
        if has_pii_residual(record, set(pii_hashes)):
            return "pii_residual", 0
        if not all(round_trips(self.tokenizer, value) for value in record.values()):
            return "tokenizer_round_trip", 0
        tokens = count_tokens(self.tokenizer, record)
        return ("too_many_tokens" if tokens > self.config.max_tokens else None), tokens

    def process_safely(self, source: PairSource) -> CleanRecord | None:
        """یک رکورد خراب کل اجرا را متوقف نمی‌کند و پیام خطایش (که ممکن است متن رزومه باشد) هیچ‌جا چاپ نمی‌شود."""
        try:
            return self.process(source)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            self._reject("invalid_record")
            return None

    def process(self, source: PairSource) -> CleanRecord | None:
        rule = _source_rejection(source, self.config)
        text = normalize_text(source.resume_text) if rule is None else ""
        rule = rule or _text_rejection(text, self.config)
        if rule:
            self._reject(rule)
            return None
        identity = with_header_name(source.identity, text)
        redactor = Redactor.for_identity(identity)
        record = build_record(source, redactor.resume_text(text), redactor)
        if self._is_duplicate(record):
            return None
        pii_hashes = identity_hashes(identity)
        rule, tokens = self._final_rejection(record, pii_hashes)
        if rule:
            self._reject(rule)
            return None
        self.counters["kept"] += 1
        return CleanRecord(record, source.candidate_key, score_bucket(source.score_ai), pii_hashes, tokens)
