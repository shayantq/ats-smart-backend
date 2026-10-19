"""تست واحد سرویس تولید سؤال (app/genai/service.py): اعتبارسنجی خروجی و یک بار اصلاح با خطاهای Schema."""

import json

import pytest

from app.genai.client import CompletionResult, GenAIOutputError
from app.genai.service import generate_questions
from tests.unit.test_genai_contract import VALID_QUESTION

PROFILE = {
    "job_posting": {"title": "Backend"},
    "candidate_profile": {"skills": ["PostgreSQL"]},
    "fit_analysis": {"strengths": [], "gaps": []},
    "resume_excerpt": "",
}
VALID = json.dumps({"focus_summary": "تمرکز بر پایگاه داده", "questions": [VALID_QUESTION] * 3}, ensure_ascii=False)


class FakeClient:
    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.calls: list[list[dict]] = []

    def complete_json(self, messages, *, schema_name, schema):
        self.calls.append(messages)
        assert schema_name == "interview_question_set" and schema["type"] == "object"
        # تعداد سؤال در Schema دقیقاً برابر نقشه قفل می‌شود
        assert schema["properties"]["questions"]["minItems"] == schema["properties"]["questions"]["maxItems"] == 3
        return CompletionResult(
            content=self.contents.pop(0),
            model="fake",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=10,
            finish_reason="stop",
        )


def _generate(client):
    return generate_questions(
        PROFILE, question_count=3, difficulty="mixed", focus_skills=[], language="fa", client=client
    )


def test_valid_first_answer_is_used_directly():
    client = FakeClient(VALID)

    result = _generate(client)

    assert len(client.calls) == 1 and result.repaired is False
    assert result.question_set.questions[0].skill == "PostgreSQL"


def test_schema_violation_gets_one_repair_round_with_the_errors():
    broken = VALID.replace('"medium"', '"expert"', 1)
    client = FakeClient(broken, VALID)

    result = _generate(client)

    assert result.repaired is True and len(client.calls) == 2
    repair_messages = client.calls[1]
    assert repair_messages[-2] == {"role": "assistant", "content": broken}
    assert "difficulty" in repair_messages[-1]["content"]
    assert (result.completion.prompt_tokens, result.completion.completion_tokens) == (200, 100)


def test_second_invalid_answer_fails_without_endless_retries():
    client = FakeClient("not json", '{"questions": []}')

    with pytest.raises(GenAIOutputError):
        _generate(client)
    assert len(client.calls) == 2


def test_fewer_questions_than_the_plan_triggers_a_repair_round():
    short = json.dumps({"focus_summary": "تمرکز بر پایگاه داده", "questions": [VALID_QUESTION]}, ensure_ascii=False)
    client = FakeClient(short, VALID)

    result = _generate(client)

    assert result.repaired is True and len(result.question_set.questions) == 3
    assert "questions" in client.calls[1][-1]["content"]
    assert len(result.plan) == 3
