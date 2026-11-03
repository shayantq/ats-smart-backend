"""تست‌های ساخت رکورد و قوانین پاک‌سازی دیتاست (app/datasets/finetune/records.py و cleanse.py) — داده‌ی ساختگی."""

import json

import pytest

from app.datasets.finetune.cleanse import CleansingConfig, Cleanser, has_pii_residual
from app.datasets.finetune.records import INSTRUCTION, JobInfo
from app.datasets.finetune.tokenization import load_tokenizer
from tests.finetune_helpers import SAMPLE_RESUME, build_test_tokenizer, sample_analysis, sample_source


@pytest.fixture(scope="module")
def tokenizer(tmp_path_factory):
    return load_tokenizer(build_test_tokenizer(tmp_path_factory.mktemp("tok")))


@pytest.fixture
def cleanser(tokenizer):
    return Cleanser(tokenizer, CleansingConfig(max_tokens=100_000))


def test_record_has_exactly_three_fields_and_deterministic_output(cleanser, tokenizer):
    first = cleanser.process(sample_source()).record
    second = Cleanser(tokenizer, CleansingConfig(max_tokens=100_000)).process(sample_source()).record
    assert list(first) == ["instruction", "input", "output"]
    assert first == second
    assert first["instruction"] == INSTRUCTION


def test_output_label_is_built_from_agent_analysis_and_hr_outcome(cleanser):
    output = json.loads(cleanser.process(sample_source()).record["output"])
    assert output["score"] == 78
    assert output["verdict"] == "مناسب"
    assert output["matched_skills"] == ["Python", "FastAPI", "PostgreSQL"]
    assert output["missing_skills"] == ["Kubernetes"]
    assert output["experience"]["total_years"] == 7.0
    assert output["experience"]["positions"] == [
        {"job_title": "برنامه‌نویس بک‌اند", "company": "فناوران ابری سپهر", "duration": "4 سال"}
    ]
    assert output["soft_skills"] == ["کار تیمی"]
    assert output["flags"] == [{"code": "invalid_period", "severity": "low", "message": "یک بازه‌ی کاری نامعتبر است"}]
    assert output["hr_outcome"] == {"status": "Technical Interview", "interview_score": 8.25}
    assert "evidence" not in json.dumps(output, ensure_ascii=False)


def test_input_contains_job_posting_and_anonymized_resume(cleanser):
    text = cleanser.process(sample_source()).record["input"]
    assert text.startswith("## آگهی شغلی\nعنوان: Backend Developer")
    assert "مهارت‌های لازم: Python، FastAPI، PostgreSQL، Kubernetes" in text
    assert "## رزومه\n[NAME]" in text
    assert "hr.jobs@example.org" not in text and "88776655" not in text  # تماس داخل متن آگهی هم حذف می‌شود


def test_draft_without_interview_has_no_hr_outcome(cleanser):
    output = json.loads(cleanser.process(sample_source(status="Draft", interview_score=None)).record["output"])
    assert output["hr_outcome"] is None


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"ambiguous_link": True}, "ambiguous_resume_link"),
        ({"resume_text": "  "}, "incomplete_resume_text"),
        ({"job": JobInfo(title="", description="")}, "incomplete_job"),
        ({"score_ai": None}, "missing_score"),
        ({"analysis": None}, "missing_agent_analysis"),
        ({"analysis": sample_analysis(status="failed")}, "missing_agent_analysis"),
        ({"score_ai": 140}, "outlier_score"),
        ({"score_ai": -3}, "outlier_score"),
        ({"analysis": sample_analysis(years=63)}, "outlier_experience_years"),
        ({"resume_text": "فرهاد فناوری" * 30}, None),
        ({"resume_text": ("فرهاد فناوری " * 30).encode("utf-8").decode("cp1252", errors="ignore")}, "mojibake"),
        ({"resume_text": "Python developer"}, "outlier_resume_too_short"),
        ({"resume_text": SAMPLE_RESUME * 40}, "outlier_resume_too_long"),
    ],
)
def test_each_cleansing_rule_rejects_and_counts(cleanser, overrides, rule):
    result = cleanser.process(sample_source(**overrides))
    if rule is None:
        assert result is not None
        return
    assert result is None
    assert cleanser.counters[rule] == 1
    assert cleanser.counters["kept"] == 0


def test_exact_and_near_duplicates_are_dropped(cleanser):
    assert cleanser.process(sample_source()) is not None
    assert cleanser.process(sample_source(candidate_key="group-2")) is None
    near = SAMPLE_RESUME.replace("2016-2019", "2015-2018").replace("—", "-")
    assert cleanser.process(sample_source(resume_text=near, candidate_key="group-3")) is None
    assert cleanser.counters["duplicate_exact"] == 1
    assert cleanser.counters["duplicate_near"] == 1
    assert cleanser.counters["kept"] == 1


def test_too_many_tokens_is_dropped(tokenizer):
    cleanser = Cleanser(tokenizer, CleansingConfig(max_tokens=50))
    assert cleanser.process(sample_source()) is None
    assert cleanser.counters["too_many_tokens"] == 1


def test_clean_record_carries_group_bucket_and_token_count(cleanser):
    clean = cleanser.process(sample_source(score_ai=55))
    assert clean.group == "group-1"
    assert clean.bucket == 2
    assert clean.tokens > 0
    assert clean.pii_hashes


def test_pii_residual_self_check_catches_leftovers():
    record = {"instruction": "x", "input": "تماس 09123456789", "output": "{}"}
    assert has_pii_residual(record, set())
    assert not has_pii_residual({"instruction": "x", "input": "[PHONE]", "output": "{}"}, set())


def test_corrupt_raw_value_is_counted_not_raised(cleanser):
    broken = sample_analysis()
    broken["experience"]["total_experience_years"] = "نامعتبر 0912"
    assert cleanser.process_safely(sample_source(analysis=broken)) is None
    assert cleanser.counters["invalid_record"] == 1


def test_technology_names_survive_validation_and_cleansing(cleanser):
    text = SAMPLE_RESUME + "\nASP.NET Core و Socket.io"
    record = cleanser.process(sample_source(resume_text=text)).record
    assert "ASP.NET Core و Socket.io" in record["input"]
