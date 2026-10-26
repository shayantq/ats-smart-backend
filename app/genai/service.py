"""
سرویس تولید بانک سؤال مصاحبه — هماهنگ‌کننده‌ی Prompt، مدل زبانی، اعتبارسنجی و ذخیره‌سازی.

    پروفایل (prompts.build_input_profile) ─► پیام‌ها ─► مدل زبانی (client) ─► JSON
        ─► اعتبارسنجی با GeneratedQuestionSet ─(نامعتبر؟ یک بار اصلاح با خطاهای Schema)─► ذخیره

اجرا همیشه در Worker صف «genai» است (app/tasks/genai.py)، نه داخل درخواست HTTP: پاسخ مدل ممکن است
ده‌ها ثانیه طول بکشد.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.genai.client import ChatCompletionsClient, CompletionResult, GenAIError, GenAIOutputError
from app.genai.contract import LLM_SCHEMA_NAME, llm_output_json_schema
from app.genai.prompts import (
    PROMPT_VERSION,
    QuestionSlot,
    build_input_profile,
    build_messages,
    build_repair_messages,
    plan_questions,
)
from app.models import Application, Candidate, InterviewQuestion, InterviewQuestionSet, Job, Resume
from app.schemas.genai import GeneratedQuestionSet

logger = logging.getLogger("ats_smart.genai")

# اولین اجرا + دو تلاش مجدد صف (app/core/queue.py) — بعد از آن خطای قابل‌تکرار هم «failed» ثبت می‌شود
MAX_ATTEMPTS = 3

_CODE_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class GenerationResult:
    question_set: GeneratedQuestionSet
    completion: CompletionResult
    repaired: bool
    plan: tuple[QuestionSlot, ...] = ()


def parse_question_set(content: str) -> GeneratedQuestionSet:
    """متن پاسخ مدل → GeneratedQuestionSet (Markdown احتمالی دور JSON حذف می‌شود)."""
    cleaned = _CODE_FENCE_PATTERN.sub("", content.strip())
    return GeneratedQuestionSet.model_validate_json(cleaned)


def generate_questions(
    profile: dict,
    *,
    question_count: int,
    difficulty: str,
    focus_skills: list[str],
    language: str,
    client: ChatCompletionsClient,
) -> GenerationResult:
    """
    فراخوانی مدل و اعتبارسنجی خروجی؛ در صورت ناسازگاری با Schema (یا تعداد سؤال متفاوت با نقشه) یک بار
    با فهرست خطاها اصلاح می‌شود.
    """
    plan = plan_questions(profile, question_count=question_count, difficulty=difficulty, focus_skills=focus_skills)
    messages = build_messages(
        profile,
        question_count=question_count,
        difficulty=difficulty,
        focus_skills=focus_skills,
        language=language,
        plan=plan,
    )
    schema = llm_output_json_schema(len(plan))
    completion = client.complete_json(messages, schema_name=LLM_SCHEMA_NAME, schema=schema)
    try:
        return GenerationResult(_parse_for_plan(completion.content, plan), completion, False, tuple(plan))
    except ValidationError as error:
        logger.warning("خروجی مدل با Schema سازگار نبود؛ یک بار اصلاح می‌شود: %s", error.error_count())
        repair = build_repair_messages(messages, completion.content, _validation_summary(error))
        second = client.complete_json(repair, schema_name=LLM_SCHEMA_NAME, schema=schema)
        try:
            question_set = _parse_for_plan(second.content, plan)
        except ValidationError as second_error:
            raise GenAIOutputError(
                "خروجی مدل پس از یک بار اصلاح هم با Schema سازگار نبود: " + _validation_summary(second_error)
            ) from second_error
        total = CompletionResult(
            content=second.content,
            model=second.model,
            prompt_tokens=_add(completion.prompt_tokens, second.prompt_tokens),
            completion_tokens=_add(completion.completion_tokens, second.completion_tokens),
            latency_ms=completion.latency_ms + second.latency_ms,
            finish_reason=second.finish_reason,
        )
        return GenerationResult(question_set, total, True, tuple(plan))


def _parse_for_plan(content: str, plan: list[QuestionSlot]) -> GeneratedQuestionSet:
    """اعتبارسنجی Schema + تعداد سؤال برابر نقشه (در حالت json_object که Schema سمت سرویس اعمال نمی‌شود)."""
    question_set = parse_question_set(content)
    if len(question_set.questions) < len(plan):
        raise ValidationError.from_exception_data(
            "GeneratedQuestionSet",
            [
                {
                    "type": "too_short",
                    "loc": ("questions",),
                    "input": len(question_set.questions),
                    "ctx": {
                        "field_type": "List",
                        "min_length": len(plan),
                        "actual_length": len(question_set.questions),
                    },
                }
            ],
        )
    return question_set


def _add(first: int | None, second: int | None) -> int | None:
    return None if first is None and second is None else (first or 0) + (second or 0)


def _validation_summary(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors(include_url=False)[:15]
    )


async def build_profile_for_application(session: AsyncSession, application: Application) -> dict:
    """پروفایل بدون اطلاعات شخصی از آخرین رزومه‌ی پردازش‌شده‌ی کارجو و آگهی همین درخواست."""
    job = await session.get(Job, application.job_id)
    candidate = await session.get(Candidate, application.candidate_id)
    resume = await latest_processed_resume(session, application.candidate_id, application.tenant_id)
    return build_input_profile(
        skill_analysis=resume.skill_analysis if resume else None,
        parsed_data=resume.parsed_data if resume else None,
        raw_text=resume.raw_text if resume else None,
        self_declared_skills=candidate.skills if candidate else None,
        match_score=application.score_ai,
        job={
            "title": job.title,
            "department": job.department,
            "required_seniority": job.required_seniority,
            "required_education": job.required_education,
            "skills_required": job.skills_required or [],
            "description": job.description,
            "location": job.location,
        },
    )


async def latest_processed_resume(
    session: AsyncSession, candidate_id: uuid.UUID, tenant_id: uuid.UUID
) -> Resume | None:
    """
    رزومه‌ی پردازش‌شده‌ی کارجو با کامل‌ترین تحلیل مهارت. جدول resumes ستون زمانی ندارد (شناسه‌ها UUID
    تصادفی‌اند)، پس «جدیدترین» قابل تشخیص نیست؛ رزومه‌ای که بیشترین مهارت از آن استخراج شده انتخاب می‌شود.

    tenant_id صریح است چون Worker در حالت system (بدون فیلتر خودکار سازمان) اجرا می‌شود: کارجویی که به
    چند سازمان درخواست داده، رزومه‌ی ارسالی به سازمان دیگر هرگز وارد Prompt این سازمان نمی‌شود.
    """
    skill_count = func.coalesce(func.jsonb_array_length(Resume.skill_analysis["skills"]), 0)
    result = await session.execute(
        select(Resume)
        .where(
            Resume.candidate_id == candidate_id,
            Resume.tenant_id == tenant_id,
            Resume.skill_analysis.is_not(None),
        )
        .order_by(skill_count.desc(), Resume.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def run_question_set_job(question_set_id: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """
    کار Worker: یک بانک سؤال pending را تولید و ذخیره می‌کند.

    خطای قابل‌تکرار (شبکه، 429، 5xx): وضعیت pending می‌ماند و استثنا دوباره پرتاب می‌شود تا صف با فاصله
    تکرار کند؛ پس از MAX_ATTEMPTS، یا با خطای غیرقابل‌تکرار، وضعیت failed با دلیل ثبت می‌شود.
    """
    async with session_factory() as session:
        question_set = await session.get(InterviewQuestionSet, question_set_id)
        if question_set is None or question_set.status not in {"pending", "processing"}:
            logger.warning("بانک سؤال %s پیدا نشد یا قبلاً پردازش شده", question_set_id)
            return
        application = await session.get(Application, question_set.application_id)
        question_set.status = "processing"
        question_set.attempts += 1
        question_set.error = None
        profile = await build_profile_for_application(session, application)
        question_set.input_profile = profile
        question_set.prompt_version = PROMPT_VERSION
        question_set.provider_model = settings.GENAI_MODEL or None
        await session.commit()
        attempts = question_set.attempts
        options = {
            "question_count": question_set.question_count,
            "difficulty": question_set.difficulty,
            "focus_skills": list(question_set.focus_skills or []),
            "language": question_set.language,
        }

    try:
        result = await asyncio.to_thread(_generate_with_settings, profile, options)
    except GenAIError as error:
        final = not error.retryable or attempts >= MAX_ATTEMPTS
        async with session_factory() as session:
            question_set = await session.get(InterviewQuestionSet, question_set_id)
            question_set.status = "failed" if final else "pending"
            question_set.error = str(error)[:2000]
            if final:
                question_set.completed_at = datetime.now(timezone.utc)
            await session.commit()
        logger.error("تولید بانک سؤال %s ناموفق (تلاش %d، نهایی=%s): %s", question_set_id, attempts, final, error)
        if not final:
            raise
        return

    async with session_factory() as session:
        question_set = await session.get(InterviewQuestionSet, question_set_id)
        generated = result.question_set
        for position, item in enumerate(generated.questions[: question_set.question_count], start=1):
            session.add(
                InterviewQuestion(
                    question_set_id=question_set.id,
                    tenant_id=question_set.tenant_id,
                    position=position,
                    category=item.category,
                    skill=item.skill,
                    difficulty=item.difficulty,
                    question=item.question,
                    purpose=item.purpose,
                    expected_answer=item.expected_answer,
                    evaluation_points=item.evaluation_points,
                    red_flags=item.red_flags,
                    follow_ups=item.follow_ups,
                    estimated_minutes=item.estimated_minutes,
                )
            )
        question_set.status = "completed"
        question_set.input_profile = {**profile, "question_plan": [slot.to_dict() for slot in result.plan]}
        question_set.focus_summary = generated.focus_summary
        question_set.prompt_tokens = result.completion.prompt_tokens
        question_set.completion_tokens = result.completion.completion_tokens
        question_set.latency_ms = result.completion.latency_ms
        question_set.completed_at = datetime.now(timezone.utc)
        await session.commit()
    logger.info(
        "بانک سؤال %s ساخته شد: %d سؤال، %s ms، اصلاح=%s",
        question_set_id,
        min(len(generated.questions), question_set.question_count),
        result.completion.latency_ms,
        result.repaired,
    )


def _generate_with_settings(profile: dict, options: dict) -> GenerationResult:
    with ChatCompletionsClient.from_settings() as client:
        return generate_questions(profile, client=client, **options)


def dump_profile(profile: dict) -> str:
    return json.dumps(profile, ensure_ascii=False, indent=2)
