import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.model_inference.budget import _load_tokenizer, check_prompt_budget
from app.model_inference.contract import AnalyzeRequest, JobContext, chat_prompt

LONG_SYNTHETIC = ("کار پژوهش و طراحی سامانه با داده‌های ساختگی ۱۴۰۲.\n" * 256).rstrip()


def test_exact_budget_allows_equality_and_exposes_the_tokenizer_hash(monkeypatch):
    def encode(prompt, *, add_special_tokens):
        assert prompt == "synthetic"
        assert add_special_tokens is False
        return SimpleNamespace(ids=[1, 2, 3])

    monkeypatch.setattr(
        "app.model_inference.budget._load_tokenizer", lambda _: (SimpleNamespace(encode=encode), "a" * 64)
    )
    equal = check_prompt_budget("synthetic", 5, 2, "configured")
    over = check_prompt_budget("synthetic", 4, 2, "configured")
    assert equal.over_by == 0
    assert over.over_by == 1
    assert over.metrics() == {
        "method": "exact",
        "prompt_tokens": 3,
        "output_reserved": 2,
        "context_limit": 4,
        "over_by": 1,
        "tokenizer_sha256": "a" * 64,
    }


def test_estimate_for_long_persian_prompt_blocks_with_no_tokenizer(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("app.model_inference.budget._warned_pid", None)
    prompt = chat_prompt(AnalyzeRequest(resume_text=LONG_SYNTHETIC, job=JobContext(title="آگهی ساختگی")))
    path = str(tmp_path / "missing")
    for _ in range(2):
        result = check_prompt_budget(
            prompt, settings.MODEL_INFERENCE_CONTEXT_LIMIT, settings.MODEL_INFERENCE_OUTPUT_LIMIT, path
        )
        assert result.method == "estimate"
        assert result.over_by > 0
        assert result.metrics()["exact_count_failed"] == 1
        assert "tokenizer_sha256" not in result.metrics()
    assert caplog.messages == ["FileNotFoundError"]


def test_estimate_is_bounded_by_exact_count_on_synthetic_persian_and_latin():
    configured_path = os.getenv("TEST_MODEL_INFERENCE_TOKENIZER_FILE")
    local_path = Path(__file__).resolve().parents[2] / "models/base-model/tokenizer.json"
    path = Path(configured_path) if configured_path else local_path
    if not configured_path and not path.is_file():
        pytest.skip(
            "مقایسهٔ تخمین و شمارش دقیق: توکنایزر محلی موجود نیست و TEST_MODEL_INFERENCE_TOKENIZER_FILE تنظیم نشده است"
        )
    assert path.is_file(), "فایل توکنایزر تنظیم‌شده برای آزمون موجود نیست"
    pytest.importorskip("tokenizers", reason="کتابخانهٔ tokenizers برای مقایسهٔ تخمین و شمارش دقیق نصب نیست")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    samples = [
        "توسعه‌دهندهٔ نرم‌افزار، سابقهٔ آموزشی از تیر ۱۴۰۲ تا اکنون.",
        "گواهی Azure، برنامه‌نویسی Python و داده‌های SQL",
        "English résumé with HTML/CSS, CI/CD, and 12 test cases.",
        ("engineering technologies collaboration " * 450) + (" " * 2000),
        ("مرحله برنامه نویسی توسعه‌دهنده " * 400) + ("ا" * 3000),
        "<|object_ref_start|> <|fim_prefix|> </tool_call> John's 1234. Ⅷ² a\u034fب",
        LONG_SYNTHETIC,
    ]
    for sample in samples:
        prompt = chat_prompt(AnalyzeRequest(resume_text=sample, job=JobContext(title="آگهی ساختگی")))
        exact = check_prompt_budget(
            prompt, settings.MODEL_INFERENCE_CONTEXT_LIMIT, settings.MODEL_INFERENCE_OUTPUT_LIMIT, str(path)
        )
        estimate = check_prompt_budget(
            prompt, settings.MODEL_INFERENCE_CONTEXT_LIMIT, settings.MODEL_INFERENCE_OUTPUT_LIMIT
        )
        assert exact.method == "exact"
        assert exact.tokenizer_sha256 == digest
        assert estimate.prompt_tokens <= exact.prompt_tokens
        assert estimate.over_by <= exact.over_by
    assert _load_tokenizer(str(path)) is _load_tokenizer(str(path))
