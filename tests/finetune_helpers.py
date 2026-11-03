"""
ابزار مشترک تست‌های دیتاست آموزش تکمیلی (tests/unit/test_finetune_*.py و tests/integration/test_finetune_pipeline.py).

توکنایزر تست در همان لحظه از روی یک متن کوچک ساختگی آموزش داده می‌شود (Byte-Level BPE، بدون دانلود)؛ رفتارش
در رفت‌وبرگشت و شمارش توکن همانند توکنایزرهای واقعی Byte-Level است. همه‌ی داده‌ها ساختگی‌اند.
"""

from __future__ import annotations

from pathlib import Path

from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

from app.datasets.finetune.anonymize import Identity
from app.datasets.finetune.records import JobInfo, PairSource

_CORPUS = [
    "برنامه‌نویس بک‌اند با پنج سال سابقه در Python و FastAPI و PostgreSQL",
    "Backend Developer with Docker, Redis and Kubernetes experience",
    "شرح شغل: توسعه‌ی سرویس‌های پرداخت و گزارش‌گیری برای تیم فنی",
    "سوابق کاری، مهارت‌ها، تحصیلات، کارشناسی ارشد مهندسی نرم‌افزار",
    '{"score": 80, "verdict": "مناسب", "matched_skills": ["Python"]}',
    "<|im_start|>system\n<|im_end|>\n<|im_start|>user\n<|im_start|>assistant\n",
]


def build_test_tokenizer(directory: Path) -> str:
    tokenizer = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=600,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        special_tokens=["<|im_start|>", "<|im_end|>"],
        show_progress=False,
    )
    tokenizer.train_from_iterator(_CORPUS * 20, trainer)
    path = directory / "tokenizer.json"
    tokenizer.save(str(path))
    return str(path)


SAMPLE_IDENTITY = Identity(
    names=("سپیده", "کوهستانی", "سپیده کوهستانی", "Sepideh Kohestani"),
    emails=("sepideh.kohestani42@example.com",),
    phones=("09123456789",),
    locations=("اصفهان",),
)

SAMPLE_RESUME = (
    "سپیده کوهستانی\n"
    "ایمیل: sepideh.kohestani42@example.com | تلفن: 0912 345 6789\n"
    "LinkedIn: linkedin.com/in/sepideh-k | Telegram: @sepidehk42\n"
    "تاریخ تولد: 1372/04/11 | کد ملی: 0012345678 | کد پستی: 81746-73111\n"
    "محل سکونت: اصفهان\n\n"
    "خلاصه\nبرنامه‌نویس بک‌اند علاقه‌مند به سیستم‌های پایدار. Sepideh Kohestani is a team player.\n\n"
    "سوابق کاری\n"
    "برنامه‌نویس بک‌اند — فناوران ابری سپهر (1398/01/01 - 1402/06/30)\n"
    "- طراحی سرویس پرداخت با Python و FastAPI و کاهش زمان پاسخ\n"
    "- راه‌اندازی استقرار خودکار با Docker و GitLab CI\n"
    "Software Engineer — Kavir Systems (2016-2019)\n"
    "- Built reporting dashboards on PostgreSQL\n\n"
    "مهارت‌ها\nPython، FastAPI، PostgreSQL، Docker، Redis\n\n"
    "تحصیلات\nکارشناسی ارشد مهندسی نرم‌افزار"
)


def sample_analysis(score: float = 78.4, years: float = 7.0, status: str = "completed") -> dict:
    return {
        "schema_version": "agents-v1",
        "status": status,
        "skills": {
            "status": "completed",
            "items": [
                {"name": name, "core": name, "category": "backend", "evidence_count": 2, "inferred": False}
                for name in ("Python", "FastAPI", "PostgreSQL", "Docker")
            ],
        },
        "experience": {
            "status": "completed",
            "total_experience_years": years,
            "entries": [
                {
                    "index": 0,
                    "company": "فناوران ابری سپهر",
                    "job_title": "برنامه‌نویس بک‌اند",
                    "duration": "4 سال",
                    "is_valid": True,
                },
                {"index": 1, "company": "Kavir Systems", "job_title": "Software Engineer", "is_valid": False},
            ],
            "overlaps": [],
            "invalid_periods": [1],
        },
        "soft_skills": {
            "status": "completed",
            "items": [
                {"key": "teamwork", "label_fa": "کار تیمی", "score": 0.8, "evidence": ["team player"]},
                {"key": "leadership", "label_fa": "رهبری", "score": 0.2, "evidence": []},
            ],
        },
        "flags": [
            {
                "code": "invalid_period",
                "severity": "low",
                "message": "یک بازه‌ی کاری نامعتبر است",
                "evidence": "Kavir Systems (2016-2019)",
                "source": "experience",
            }
        ],
        "matching": {"score": score, "matched_required_skills": ["Python", "FastAPI", "PostgreSQL"]},
    }


SAMPLE_JOB = JobInfo(
    title="Backend Developer",
    department="فنی",
    description="توسعه‌ی سرویس‌های پرداخت. برای سؤال با hr.jobs@example.org یا 021-88776655 تماس بگیرید.",
    skills_required=("Python", "FastAPI", "PostgreSQL", "Kubernetes"),
    seniority="senior",
    education="کارشناسی",
)


def sample_source(**overrides) -> PairSource:
    values = {
        "candidate_key": "group-1",
        "score_ai": 78,
        "status": "Technical Interview",
        "job": SAMPLE_JOB,
        "resume_text": SAMPLE_RESUME,
        "analysis": sample_analysis(),
        "identity": SAMPLE_IDENTITY,
        "interview_score": 8.25,
    }
    values.update(overrides)
    return PairSource(**values)
