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
from app.core.employment_evidence import extract_employment, analyze_evidence
from app.core.resume_parser import parse_resume_text
from app.core.service_auth import issue_service_token
from app.core.text_extraction import extract_raw_text
from app.model_inference.client import InferenceClient, InferenceError
from app.model_inference.contract import AnalyzeRequest, AnalyzeResponse, JobContext


def map_analysis(response: AnalyzeResponse, raw_text: str, parsed: dict, elapsed_ms: float) -> UnifiedAnalysis:
    prediction = response.analysis
    # تطبیق مهارت با گراف واقعی باقی می‌ماند؛ برچسب مدل معادل شاهد مستقیم متن نیست.
    skills = run_skill_agent(raw_text, parsed)
    employment, total_years = analyze_evidence(extract_employment(raw_text, layout=parsed.get("_extraction")))
    supported_entries = [ExperienceEntry(index=i, **entry) for i, entry in enumerate(employment)]
    flags = [Flag(**flag.model_dump(), source="model_prediction") for flag in prediction.flags]
    flags.append(
        Flag(
            code="MODEL_REVIEW_REQUIRED",
            severity="medium",
            message="این ارزیابی پیش‌بینی مدل آموزش‌دیده با دادهٔ ساختگی است و نیاز به بررسی انسانی دارد.",
            source="model_prediction",
        )
    )
    if prediction.experience.positions:
        flags.append(
            Flag(
                code="MODEL_EMPLOYMENT_NOT_AUTHORITATIVE",
                severity="medium",
                message="پیش‌بینی سوابق مدل مبنای سابقه نیست؛ فقط شواهد بخش سوابق رزومه نمایش داده می‌شود.",
                source="source_validation",
            )
        )
    return UnifiedAnalysis(
        status="partial",
        skills=UnifiedSkills(status=skills.status, items=skills.skills),
        experience=UnifiedExperience(
            status="completed" if supported_entries else "failed",
            total_experience_years=total_years,
            entries=supported_entries,
        ),
        soft_skills=UnifiedSoftSkills(status="failed"),
        matching=Matching(score=prediction.score, matched_required_skills=prediction.matched_skills),
        flags=flags,
        errors={
            **({"experience": "employment_evidence_unavailable"} if not supported_entries else {}),
            "soft_skills": "model_output_has_no_evidence",
        },
        timings_ms={"total": Timing(start_ms=0, end_ms=elapsed_ms, duration_ms=elapsed_ms)},
    )


@dataclass
class ModelResult:
    raw_text: str
    parsed_data: dict | None
    analysis: UnifiedAnalysis
    metrics: dict | None = None


async def run_model_pipeline(
    file_bytes: bytes,
    filename: str,
    job_context: dict | None,
    *,
    saved_text: str | None = None,
    saved_parsed: dict | None = None,
    saved_layout: dict | None = None,
    persist=None,
) -> ModelResult:
    """واسط ذخیرهٔ مرحله‌ای پیش از شبکه اجرا می‌شود؛ اعتبار نسخهٔ فایل با فراخواننده است."""
    started = time.perf_counter()
    metrics = {"reused_extraction": saved_text is not None, "reused_parsing": saved_parsed is not None}
    stage = time.perf_counter()
    raw_text = (
        saved_text
        if saved_text is not None
        else await asyncio.to_thread(extract_raw_text, file_bytes, filename=filename, with_layout=True)
    )
    layout = saved_layout
    if isinstance(raw_text, dict):
        layout = {k: v for k, v in raw_text.items() if k != "raw_text"}
        raw_text = raw_text["raw_text"]
    metrics["extraction_ms"] = (time.perf_counter() - stage) * 1000
    if persist:
        await persist(raw_text, {"_extraction": layout} if layout else None, "parsing", dict(metrics))
    stage = time.perf_counter()
    parsed = (
        saved_parsed
        if saved_parsed is not None
        else (
            await asyncio.to_thread(parse_resume_text, raw_text, **({"layout": layout} if layout else {}))
        ).model_dump()
    )
    metrics["parsing_ms"] = (time.perf_counter() - stage) * 1000
    if layout:
        parsed = dict(parsed, _extraction=layout)
    from app.core.analysis_evidence import build_analysis

    if parsed.get("structured"):
        parsed = dict(
            parsed,
            _evidence_analysis=await asyncio.to_thread(
                build_analysis, raw_text, parsed["structured"], job_context, layout
            ),
        )
    if persist:
        await persist(raw_text, parsed, "inference", dict(metrics))
    source = job_context or {}
    job_values = {key: source[key] for key in JobContext.model_fields if key in source}
    job_values["skills_required"] = source.get("skills_required") or []
    job = JobContext.model_validate(job_values)
    stage = time.perf_counter()
    # Worker فعلی برای هر job یک loop می‌سازد؛ pool متعلق به همان loop است و پایان job بسته می‌شود.
    try:
        async with InferenceClient(
            settings.MODEL_INFERENCE_URL,
            lambda: issue_service_token(audience="ats-inference"),
            timeout=settings.MODEL_INFERENCE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.analyze(AnalyzeRequest(resume_text=raw_text, job=job))
    except InferenceError as error:
        metrics.update(error.metrics)
        metrics["model_request_ms"] = (time.perf_counter() - stage) * 1000
        if persist:
            await persist(raw_text, parsed, "inference", dict(metrics))
        raise
    metrics["model_request_ms"] = (time.perf_counter() - stage) * 1000
    metrics.update(input_tokens=response.input_tokens, output_tokens=response.output_tokens)
    metrics.update(response.timings_ms)
    stage = time.perf_counter()
    analysis = await asyncio.to_thread(map_analysis, response, raw_text, parsed, (time.perf_counter() - started) * 1000)
    metrics["mapping_ms"] = (time.perf_counter() - stage) * 1000
    return ModelResult(raw_text, parsed, analysis, metrics)
