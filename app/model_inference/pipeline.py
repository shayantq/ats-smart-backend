"""نگاشت صریح پیش‌بینی مدل به قرارداد فعلی؛ اطلاعات تأییدنشده معتبر جا زده نمی‌شود."""

import asyncio
import time
from dataclasses import dataclass

from app.agents.schema import (
    ExperienceEntry,
    Flag,
    Matching,
    Timing,
    UnifiedAnalysis,
    UnifiedExperience,
    UnifiedSkills,
    UnifiedSoftSkills,
)
from app.agents.skill_agent import run_skill_agent
from app.core.config import settings
from app.core.resume_parser import parse_resume_text
from app.core.service_auth import issue_service_token
from app.core.text_extraction import extract_raw_text
from app.model_inference.client import InferenceClient
from app.model_inference.contract import AnalyzeRequest, AnalyzeResponse, JobContext


def map_analysis(response: AnalyzeResponse, raw_text: str, parsed: dict, elapsed_ms: float) -> UnifiedAnalysis:
    prediction = response.analysis
    # تطبیق مهارت با گراف واقعی باقی می‌ماند؛ برچسب مدل معادل شاهد مستقیم متن نیست.
    skills = run_skill_agent(raw_text, parsed)
    flags = [Flag(**flag.model_dump(), source="model_prediction") for flag in prediction.flags]
    flags.append(
        Flag(
            code="MODEL_REVIEW_REQUIRED",
            severity="medium",
            message="این ارزیابی پیش‌بینی مدل آموزش‌دیده با دادهٔ ساختگی است و نیاز به بررسی انسانی دارد.",
            source="model_prediction",
        )
    )
    return UnifiedAnalysis(
        status="partial",
        skills=UnifiedSkills(status=skills.status, items=skills.skills),
        experience=UnifiedExperience(
            status="failed",
            total_experience_years=prediction.experience.total_years,
            entries=[
                ExperienceEntry(
                    index=index,
                    **position.model_dump(),
                    is_valid=False,
                    flag_reason="سابقهٔ پیش‌بینی‌شده؛ تاریخ‌ها مستقلاً اعتبارسنجی نشده‌اند.",
                )
                for index, position in enumerate(prediction.experience.positions)
            ],
        ),
        soft_skills=UnifiedSoftSkills(status="failed"),
        matching=Matching(score=prediction.score, matched_required_skills=prediction.matched_skills),
        flags=flags,
        errors={
            "experience": "model_prediction_unverified",
            "soft_skills": "model_output_has_no_evidence",
        },
        timings_ms={"total": Timing(start_ms=0, end_ms=elapsed_ms, duration_ms=elapsed_ms)},
    )


@dataclass
class ModelResult:
    raw_text: str
    parsed_data: dict | None
    analysis: UnifiedAnalysis


async def run_model_pipeline(file_bytes: bytes, filename: str, job_context: dict | None) -> ModelResult:
    started = time.perf_counter()
    raw_text = await asyncio.to_thread(extract_raw_text, file_bytes, filename=filename)
    parsed = await asyncio.to_thread(parse_resume_text, raw_text)
    source = job_context or {}
    job_values = {key: source[key] for key in JobContext.model_fields if key in source}
    job_values["skills_required"] = source.get("skills_required") or []
    job = JobContext.model_validate(job_values)
    # Worker فعلی برای هر job یک loop می‌سازد؛ pool متعلق به همان loop است و پایان job بسته می‌شود.
    async with InferenceClient(
        settings.MODEL_INFERENCE_URL,
        lambda: issue_service_token(audience="ats-inference"),
        timeout=settings.MODEL_INFERENCE_TIMEOUT_SECONDS,
    ) as client:
        response = await client.analyze(AnalyzeRequest(resume_text=raw_text, job=job))
    analysis = await asyncio.to_thread(
        map_analysis, response, raw_text, parsed.model_dump(), (time.perf_counter() - started) * 1000
    )
    return ModelResult(raw_text, parsed.model_dump(), analysis)
