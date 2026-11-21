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
from app.core.resume_dates import normalize
from app.core.resume_parser import parse_resume_text
from app.core.service_auth import issue_service_token
from app.core.skill_evidence import CANONICAL, mentions
from app.core.text_extraction import extract_raw_text
from app.model_inference.budget import check_prompt_budget, configured_tokenizer_sha256
from app.model_inference.client import InferenceClient, InferenceError
from app.model_inference.contract import (
    AnalyzeRequest,
    AnalyzeResponse,
    EVIDENCE_INPUT_TOKENS,
    EVIDENCE_OUTPUT_TOKENS,
    EvidenceCheck,
    JobContext,
    VerifyEvidenceRequest,
    chat_prompt,
    evidence_prompt,
)
from app.model_inference.resume_digest import ResumeDigestBuilder, digest_level

MODEL_EVIDENCE_POLICY_VERSION = "matching-evidence-v1"
LIMITED_EVIDENCE_INPUT_TOKENS = 160


def validate_model_evidence(
    analysis: UnifiedAnalysis,
    evidence: dict,
    *,
    incomplete_input: bool = False,
    checked_skills: list[str] | None = None,
) -> dict[str, int]:
    if incomplete_input:
        code = "MODEL_SCORE_EVIDENCE_INCOMPLETE"
        message = "شواهد رزومه برای نمایش امتیاز مدل کافی نیست. پرونده نیازمند بازبینی است."
    else:
        if checked_skills is not None:
            expected = dict.fromkeys(checked_skills, True)
        else:
            expected = {}
            for row in evidence.get("requirements") or []:
                expression = row.get("expression") or {}
                skill = expression.get("skill")
                # خروجی مدل نام مهارت است و قیود نسخه، مدت یا شرط ترکیبی را بیان نمی‌کند.
                if (
                    row.get("source") == "skills_required"
                    and skill
                    and not (expression.get("version") or expression.get("minimum_years") is not None)
                ):
                    expected[skill] = row.get("status") == "met"
        predicted = {CANONICAL.get(normalize(skill)) for skill in analysis.matching.matched_required_skills}
        if all((skill in predicted) == supported for skill, supported in expected.items()):
            return {}
        code = "MODEL_MATCHING_EVIDENCE_CONFLICT"
        message = "تطبیق مدل با شواهد شروط آگهی همخوانی ندارد. پوشش مستند در پرونده در دسترس است."

    analysis.matching.score = None
    analysis.matching.matched_required_skills.clear()
    analysis.flags = [flag for flag in analysis.flags if flag.source != "model_prediction"]
    analysis.flags.append(Flag(code=code, severity="medium", source="source_validation", message=message))
    return {"model_score_suppressed": 1, "model_matching_conflict": int(code == "MODEL_MATCHING_EVIDENCE_CONFLICT")}


def map_analysis(response: AnalyzeResponse, raw_text: str, parsed: dict, elapsed_ms: float) -> UnifiedAnalysis:
    prediction = response.analysis
    # تطبیق مهارت با گراف واقعی باقی می‌ماند؛ برچسب مدل معادل شاهد مستقیم متن نیست.
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
    result = source_analysis(raw_text, parsed, elapsed_ms)
    result.matching = Matching(score=prediction.score, matched_required_skills=prediction.matched_skills)
    result.flags = flags
    return result


def source_analysis(raw_text: str, parsed: dict, elapsed_ms: float) -> UnifiedAnalysis:
    skills = run_skill_agent(raw_text, parsed)
    employment, total_years = analyze_evidence(extract_employment(raw_text, layout=parsed.get("_extraction")))
    supported_entries = [ExperienceEntry(index=i, **entry) for i, entry in enumerate(employment)]
    return UnifiedAnalysis(
        status="partial",
        skills=UnifiedSkills(status=skills.status, items=skills.skills),
        experience=UnifiedExperience(
            status="completed" if supported_entries else "failed",
            total_experience_years=total_years,
            entries=supported_entries,
        ),
        soft_skills=UnifiedSoftSkills(status="failed"),
        matching=Matching(),
        errors={
            **({"experience": "employment_evidence_unavailable"} if not supported_entries else {}),
            "soft_skills": "model_output_has_no_evidence",
        },
        timings_ms={"total": Timing(start_ms=0, end_ms=elapsed_ms, duration_ms=elapsed_ms)},
    )


def evidence_checks(parsed: dict, layout: dict | None, *, allow_subset: bool = False) -> VerifyEvidenceRequest | None:
    if (layout or {}).get("status") == "partial":
        return None
    requirements = [
        row
        for row in (parsed.get("_evidence_analysis") or {}).get("requirements", [])
        if row.get("priority") == "required"
    ]
    if not allow_subset and not 1 <= len(requirements) <= 4:
        return None
    checks = []
    for row in requirements:
        expression = row.get("expression") or {}
        skill = expression.get("skill")
        if (
            row.get("source") != "skills_required"
            or row.get("status") != "met"
            or not skill
            or expression.get("version")
            or expression.get("minimum_years") is not None
        ):
            if allow_subset:
                continue
            return None
        excerpts = [ref.get("text", "").strip() for ref in expression.get("evidence", [])]
        matches = [
            excerpt
            for excerpt in excerpts
            if 1 <= len(excerpt) <= 160 and any(name == skill for name, *_ in mentions(excerpt))
        ]
        if not matches:
            if allow_subset:
                continue
            return None
        checks.append(EvidenceCheck(skill=skill, excerpt=min(matches, key=len)))
    if allow_subset and checks:
        # یک شاهد کوتاه برای زمان پاسخ روی CPU کافی است؛ ماتریس شروط کامل باقی می‌ماند.
        checks = [min(checks, key=lambda check: len(check.skill) + len(check.excerpt))]
    return VerifyEvidenceRequest(checks=checks) if checks else None


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
    resolve_limits=None,
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
    limits = resolve_limits() if resolve_limits is not None else None
    if persist:
        await persist(raw_text, parsed, "inference", dict(metrics))
    source = job_context or {}
    job_values = {key: source[key] for key in JobContext.model_fields if key in source}
    job_values["skills_required"] = source.get("skills_required") or []
    job = JobContext.model_validate(job_values)
    context_limit = settings.MODEL_INFERENCE_CONTEXT_LIMIT
    output_limit = settings.MODEL_INFERENCE_OUTPUT_LIMIT
    tokenizer_path = settings.MODEL_INFERENCE_TOKENIZER_FILE
    if limits is not None:
        metrics["limits_synced"] = 1
        if (limits.context_limit, limits.output_limit) != (context_limit, output_limit):
            metrics["limits_mismatch"] = 1
        context_limit, output_limit = limits.context_limit, limits.output_limit
        if (
            tokenizer_path
            and await asyncio.to_thread(configured_tokenizer_sha256, tokenizer_path) != limits.tokenizer_sha256
        ):
            tokenizer_path = ""
            metrics["tokenizer_hash_mismatch"] = 1

    def measure(text: str):
        prompt = chat_prompt(AnalyzeRequest.model_construct(resume_text=text, job=job))
        return check_prompt_budget(prompt, context_limit, output_limit, tokenizer_path)

    mode = settings.RESUME_MODEL_INPUT
    raw_budget = None
    evidence_limited = False
    checks = evidence_checks(parsed, layout) if settings.MODEL_EVIDENCE_CHECK_ENABLED else None
    if settings.MODEL_EVIDENCE_CHECK_ENABLED and mode == "raw" and checks is None:
        selected = evidence_checks(parsed, layout, allow_subset=True)
        if selected:
            raw_budget = await asyncio.to_thread(measure, raw_text)
            if raw_budget.over_by:
                checks = selected
                evidence_limited = True
                metrics.update(raw_budget.metrics())
    if checks:
        prompt_limit = LIMITED_EVIDENCE_INPUT_TOKENS if evidence_limited else EVIDENCE_INPUT_TOKENS
        evidence_budget = await asyncio.to_thread(
            check_prompt_budget,
            evidence_prompt(checks),
            min(context_limit, prompt_limit + EVIDENCE_OUTPUT_TOKENS),
            EVIDENCE_OUTPUT_TOKENS,
            tokenizer_path,
        )
        if not evidence_budget.over_by:
            if evidence_limited:
                metrics["evidence_prompt_tokens"] = evidence_budget.prompt_tokens
            else:
                metrics.update(evidence_budget.metrics())
            stage = time.perf_counter()
            async with InferenceClient(
                settings.MODEL_INFERENCE_URL,
                lambda: issue_service_token(audience="ats-inference"),
                timeout=min(settings.MODEL_INFERENCE_TIMEOUT_SECONDS, 40),
            ) as client:
                verdict = await client.verify_evidence(checks)
        else:
            verdict = None
        if verdict is not None:
            request_ms = (time.perf_counter() - stage) * 1000
            if len(verdict.matches) != len(checks.checks):
                raise InferenceError("invalid_inference_response", 502)
            matches = [check.skill for check, supported in zip(checks.checks, verdict.matches) if supported]
            analysis = await asyncio.to_thread(
                source_analysis, raw_text, parsed, (time.perf_counter() - started) * 1000
            )
            analysis.matching.matched_required_skills = matches
            conflict = validate_model_evidence(
                analysis,
                parsed.get("_evidence_analysis") or {},
                checked_skills=[check.skill for check in checks.checks] if evidence_limited else None,
            )
            if not conflict:
                analysis.flags.append(
                    Flag(
                        code="MODEL_EVIDENCE_VERIFIED",
                        severity="low",
                        source="source_validation",
                        message="مدل حضور مهارت‌های مستند را در شاهدهای رزومه بررسی کرد.",
                    )
                )
            metrics.update(verdict.timings_ms)
            metrics.update(conflict)
            if evidence_limited:
                analysis.flags.append(
                    Flag(
                        code="MODEL_EVIDENCE_BUDGET_LIMITED",
                        severity="low",
                        source="source_validation",
                        message=(
                            "به‌دلیل طول رزومه، بررسی مدل به یک شاهد مهارتی محدود شد. "
                            "پوشش همهٔ شروط در پرونده موجود است."
                        ),
                    )
                )
                metrics["evidence_budget_limited"] = 1
            metrics.update(
                input_tokens=verdict.input_tokens,
                output_tokens=verdict.output_tokens,
                model_request_ms=request_ms,
                evidence_checked=len(checks.checks),
                evidence_agreements=len(matches),
                model_score_suppressed=1,
            )
            return ModelResult(raw_text, parsed, analysis, metrics)

    model_text = raw_text
    incomplete_model_input = mode != "raw" and (layout or {}).get("status") == "partial"
    if mode != "raw":

        def build_digest():
            builder = ResumeDigestBuilder(
                raw_text, parsed.get("structured") or {}, layout, icon_fonts=settings.RESUME_DIGEST_ICON_FONTS
            )
            level = digest_level(mode)
            if level == 2 and not builder.coverage["assigned"]:
                level = 0
            digest = builder.build(level, measure, cap=settings.RESUME_DIGEST_DESCRIPTION_CAP)
            overhead = measure("").prompt_tokens if digest and digest.cap_used is not None else 0
            return measure(raw_text), digest, overhead

        raw_budget, digest, overhead = await asyncio.to_thread(build_digest)
        if digest is None:
            metrics.update(digest_marker_collision=1, effective_input_mode="raw")
            budget = raw_budget
        else:
            model_text, budget = digest.text, digest.budget
            omitted_chars = sum(digest.omitted_by_record.values()) + digest.unassigned_omitted
            incomplete_model_input |= digest.level == 2 and omitted_chars > 0
            if mode == "digest_l2" and digest.level == 0:
                metrics["digest_compaction_skipped_no_evidence"] = 1
                incomplete_model_input = True
            metrics.update(
                digest_level=digest.level,
                raw_tokens=raw_budget.prompt_tokens,
                digest_tokens=budget.prompt_tokens,
                coverage_pct=digest.coverage["coverage_pct"],
                unassigned_chars=digest.coverage["unassigned"],
                omitted_chars=omitted_chars,
                ambiguous_attribution=digest.coverage["ambiguous_attribution"],
            )
            if digest.cap_used is not None:
                metrics.update(
                    cap_used=digest.cap_used,
                    tokens_used=max(0, budget.prompt_tokens - overhead),
                    budget=max(0, budget.context_limit - budget.output_reserved - overhead),
                )
    else:
        request = AnalyzeRequest(resume_text=raw_text, job=job)
        budget = raw_budget or await asyncio.to_thread(measure, request.resume_text)
    metrics.update(budget.metrics())
    if budget.over_by:
        if persist:
            await persist(raw_text, parsed, "inference", dict(metrics))
        raise InferenceError("input_exceeds_model_budget", 422)
    if mode != "raw":
        request = AnalyzeRequest(resume_text=model_text, job=job)
    stage = time.perf_counter()
    # Worker فعلی برای هر job یک loop می‌سازد؛ pool متعلق به همان loop است و پایان job بسته می‌شود.
    try:
        async with InferenceClient(
            settings.MODEL_INFERENCE_URL,
            lambda: issue_service_token(audience="ats-inference"),
            timeout=settings.MODEL_INFERENCE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.analyze(request)
    except InferenceError as error:
        if error.code == "context_limit_exceeded" and error.status_code == 422:
            metrics["preflight_gateway_mismatch"] = 1
            metrics["preflight_context_limit"] = budget.context_limit
        metrics.update(error.metrics)
        metrics["model_request_ms"] = (time.perf_counter() - stage) * 1000
        if persist:
            await persist(raw_text, parsed, "inference", dict(metrics))
        raise
    metrics["model_request_ms"] = (time.perf_counter() - stage) * 1000
    metrics.update(input_tokens=response.input_tokens, output_tokens=response.output_tokens)
    metrics.update(response.timings_ms)
    timing = response.timings_ms
    prompt_tokens = timing.get("engine_prompt_tokens")
    prefill, generation = timing.get("engine_prompt_ms"), timing.get("engine_predicted_ms")
    metrics.update(
        engine_prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
        engine_output_tokens=response.output_tokens,
        prefill_ms=prefill,
        generation_ms=generation,
        engine_total_ms=prefill + generation if prefill is not None and generation is not None else None,
    )
    stage = time.perf_counter()
    analysis = await asyncio.to_thread(map_analysis, response, raw_text, parsed, (time.perf_counter() - started) * 1000)
    if mode != "raw":
        metrics.update(
            validate_model_evidence(
                analysis, parsed.get("_evidence_analysis") or {}, incomplete_input=incomplete_model_input
            )
        )
    metrics["mapping_ms"] = (time.perf_counter() - stage) * 1000
    return ModelResult(raw_text, parsed, analysis, metrics)
