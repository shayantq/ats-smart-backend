"""اعتبارسنجی کامل مرز شبکه؛ خروجی مدل هرگز تصمیم واقعی منابع انسانی نیست."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class JobContext(Strict):
    title: str = Field(max_length=300)
    department: str | None = Field(default=None, max_length=300)
    skills_required: list[str] = Field(default_factory=list, max_length=100)
    required_seniority: str | None = Field(default=None, max_length=100)
    required_education: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=12000)


class AnalyzeRequest(Strict):
    resume_text: str = Field(min_length=1, max_length=24000)
    job: JobContext


class Position(Strict):
    job_title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)
    duration: str | None = Field(default=None, max_length=100)


class Experience(Strict):
    total_years: float = Field(ge=0, le=100)
    positions: list[Position] = Field(max_length=10)
    overlaps: int = Field(ge=0, le=100)
    invalid_periods: int = Field(ge=0, le=100)


class ModelFlag(Strict):
    code: str = Field(max_length=100)
    severity: Literal["low", "medium", "high"]
    message: str = Field(max_length=1000)


class GeneratedOutcome(Strict):
    status: str | None = Field(max_length=100)
    interview_score: float | None = Field(ge=0, le=100)


class GeneratedAnalysis(Strict):
    score: int = Field(ge=0, le=100)
    verdict: str = Field(min_length=1, max_length=200)
    matched_skills: list[str] = Field(max_length=100)
    missing_skills: list[str] = Field(max_length=100)
    experience: Experience
    soft_skills: list[str] = Field(max_length=5)
    flags: list[ModelFlag] = Field(max_length=50)
    hr_outcome: GeneratedOutcome | None
    rationale: str = Field(min_length=1, max_length=4000)


class Analysis(GeneratedAnalysis):
    # این فیلد عمداً در مرز سرویس پاک می‌شود و کلاینت نیز null بودنش را کنترل می‌کند.
    hr_outcome: None


class AnalyzeResponse(Strict):
    schema_version: Literal["ats-inference-v1"] = "ats-inference-v1"
    analysis: Analysis
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model: str


INSTRUCTION = (
    "شما کارشناس ارشد جذب و استخدام در بازار کار ایران هستید. رزومه‌ی زیر را با آگهی شغلی مقایسه و ارزیابی کنید. "
    "پاسخ را فقط به‌صورت یک شیء JSON با این کلیدها برگردانید: score (عدد صحیح 0 تا 100)، verdict، matched_skills، "
    "missing_skills، experience، soft_skills، flags، hr_outcome و rationale. اطلاعات هویتی کارجو با برچسب‌هایی مثل "
    "[NAME]، [EMAIL] و [PHONE] جایگزین شده است؛ آن‌ها را حدس نزنید و در ارزیابی دخالت ندهید."
)


def user_input(request: AnalyzeRequest) -> str:
    job = request.job
    lines = [f"عنوان: {job.title}"]
    for label, value in (
        ("دپارتمان", job.department),
        ("سطح ارشدیت", job.required_seniority),
        ("تحصیلات لازم", job.required_education),
    ):
        if value:
            lines.append(f"{label}: {value}")
    if job.skills_required:
        lines.append("مهارت‌های لازم: " + "، ".join(job.skills_required))
    if job.description:
        lines.append("شرح:\n" + job.description)
    return "## آگهی شغلی\n" + "\n".join(lines) + "\n\n## رزومه\n" + request.resume_text


def chat_prompt(request: AnalyzeRequest) -> str:
    # همان قالب ChatML توکنایزر پایه؛ raw در موتور از افزودن قالب دوم جلوگیری می‌کند.
    return (
        f"<|im_start|>system\n{INSTRUCTION}<|im_end|>\n"
        f"<|im_start|>user\n{user_input(request)}<|im_end|>\n<|im_start|>assistant\n"
    )
