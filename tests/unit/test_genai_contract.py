"""تست واحد قراردادهای GenAI: JSON Schema خروجی مدل (strict) و هم‌خوانی فایل‌های docs/genai با کد."""

import json

import pytest
from pydantic import ValidationError

from app.genai.contract import OPENAPI_PATH, SCHEMA_PATH, llm_output_json_schema, openapi_contract, render
from app.genai.service import parse_question_set

VALID_QUESTION = {
    "category": "technical",
    "skill": "PostgreSQL",
    "difficulty": "medium",
    "question": "برای یک جدول پرتراکنش، ایندکس مناسب جستجو بر اساس دو ستون را چطور انتخاب می‌کنید؟",
    "purpose": "نقطه‌ی قوت: مهارت اجباری PostgreSQL",
    "expected_answer": "ایندکس مرکب با ترتیب ستون بر اساس انتخاب‌پذیری و الگوی کوئری؛ بررسی با EXPLAIN ANALYZE",
    "evaluation_points": ["ترتیب ستون‌ها", "EXPLAIN ANALYZE"],
    "red_flags": ["ایندکس روی همه‌ی ستون‌ها"],
    "follow_ups": ["ایندکس جزئی چه زمانی؟"],
    "estimated_minutes": 5,
}


def _walk_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from _walk_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item)


def test_llm_schema_is_strict_and_self_contained():
    schema = llm_output_json_schema()

    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    objects = list(_walk_objects(schema))
    assert len(objects) == 2  # مجموعه + سؤال
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])  # همه‌ی فیلدها اجباری (strict)
    question = schema["properties"]["questions"]["items"]
    assert question["properties"]["difficulty"]["enum"] == ["easy", "medium", "hard"]


def test_valid_output_parses_even_inside_a_markdown_fence():
    payload = json.dumps(
        {"focus_summary": "تمرکز بر داده و توزیع‌شدگی", "questions": [VALID_QUESTION]}, ensure_ascii=False
    )

    result = parse_question_set(f"```json\n{payload}\n```")

    assert result.questions[0].skill == "PostgreSQL"


@pytest.mark.parametrize(
    "mutation",
    [
        {"difficulty": "expert"},
        {"category": "trivia"},
        {"evaluation_points": []},
        {"estimated_minutes": 90},
        {"extra": 1},
    ],
)
def test_invalid_output_is_rejected(mutation):
    question = {**VALID_QUESTION, **mutation}
    payload = json.dumps({"focus_summary": "خلاصه‌ی محورها", "questions": [question]}, ensure_ascii=False)

    with pytest.raises(ValidationError):
        parse_question_set(payload)


def test_committed_contract_files_match_the_code():
    """بعد از تغییر اسکیماها یا مسیرها: python -m app.genai.contract"""
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render(llm_output_json_schema())
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render(openapi_contract())


def test_openapi_contract_covers_every_genai_endpoint():
    paths = openapi_contract()["paths"]

    assert set(paths) == {
        "/api/v1/genai/interview-questions",
        "/api/v1/genai/interview-questions/{set_id}",
        "/api/v1/genai/interview-questions/{set_id}/questions/{question_id}",
        "/api/v1/genai/question-bank",
    }
    assert set(paths["/api/v1/genai/interview-questions"]) == {"get", "post"}
    assert "202" in paths["/api/v1/genai/interview-questions"]["post"]["responses"]
