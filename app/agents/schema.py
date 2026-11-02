"""
قرارداد خروجی اکوسیستم چندعاملی پردازش رزومه — JSON یکپارچه‌ی عامل ناظر (Supervisor).

همه‌ی مدل‌ها extra="forbid" دارند: کلید ناشناخته یا تکراری از یک عامل به خروجی نهایی راه پیدا نمی‌کند و
نوع هر فیلد ثابت است (مثلاً سال‌ها همیشه float، مهارت‌ها همیشه نام استاندارد گراف مهارت). نسخه‌ی قرارداد در
schema_version است؛ تغییر ناسازگار = نسخه‌ی جدید.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "agents-v1"

AgentStatus = Literal["completed", "failed"]
Severity = Literal["low", "medium", "high"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Flag(_Strict):
    """هشدار اعتبارسنجی (بزرگ‌نمایی، تاریخ نامعتبر، تداخل) — evidence کوتاه از متن، فقط برای نمایش به HR."""

    code: str
    severity: Severity
    message: str
    evidence: Optional[str] = None
    source: str  # نام عاملی که هشدار را داده است


# ---------------------------------------------------------------------------
# عامل ۱: استخراج مهارت
# ---------------------------------------------------------------------------
class SkillItem(_Strict):
    name: str  # نام استاندارد در گراف مهارت (app/core/skill_graph.py)
    core: str  # مهارت اصلی/گره والد
    category: str
    evidence_count: int = Field(ge=0)  # تعداد دفعات ذکر مستقیم در متن
    inferred: bool  # فقط از روی زیرشاخه استنتاج شده (مثلاً Python از FastAPI)
    confidence: float = Field(ge=0, le=1)
    claimed_years: Optional[float] = Field(default=None, ge=0)  # ادعای متن، مثلاً «۸ سال Python»


class SkillAgentOutput(_Strict):
    status: AgentStatus
    error: Optional[str] = None
    skills: list[SkillItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# عامل ۲: اعتبارسنجی سوابق کاری
# ---------------------------------------------------------------------------
class ExperienceEntry(_Strict):
    index: int
    company: Optional[str] = None
    job_title: Optional[str] = None
    duration: Optional[str] = None
    start_year: Optional[int] = None  # همان تقویم متن رزومه
    end_year: Optional[int] = None
    start_year_gregorian: Optional[int] = None  # یکسان‌شده برای مقایسه‌ی شمسی/میلادی
    end_year_gregorian: Optional[int] = None
    is_valid: bool
    flag_reason: Optional[str] = None


class Overlap(_Strict):
    entries: tuple[int, int]
    years: float = Field(gt=0)


class ExperienceAgentOutput(_Strict):
    status: AgentStatus
    error: Optional[str] = None
    entries: list[ExperienceEntry] = Field(default_factory=list)
    total_experience_years: float = 0.0
    overlaps: list[Overlap] = Field(default_factory=list)
    invalid_periods: list[int] = Field(default_factory=list)
    claimed_total_years: Optional[float] = None
    flags: list[Flag] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# عامل ۳: تناسب فرهنگی و مهارت‌های نرم
# ---------------------------------------------------------------------------
class SoftSkillItem(_Strict):
    key: str
    label_fa: str
    score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)  # عبارت‌های واژه‌نامه که در متن دیده شد


class ToneProfile(_Strict):
    confident: float = Field(ge=0)  # تکرار در هر ۱۰۰ کلمه
    collaborative: float = Field(ge=0)
    individual: float = Field(ge=0)
    hedging: float = Field(ge=0)
    passive_voice_ratio: float = Field(ge=0, le=1)
    dominant: str


class SoftSkillsAgentOutput(_Strict):
    status: AgentStatus
    error: Optional[str] = None
    soft_skills: list[SoftSkillItem] = Field(default_factory=list)
    tone: Optional[ToneProfile] = None
    word_count: int = 0
    confidence: float = Field(default=0.0, ge=0, le=1)


# ---------------------------------------------------------------------------
# عامل ناظر: خروجی یکپارچه
# ---------------------------------------------------------------------------
class ConflictResolution(_Strict):
    code: str
    agents: list[str]
    description: str
    resolution: str


class Matching(_Strict):
    score: Optional[float] = Field(default=None, ge=0, le=100)
    base_score: Optional[float] = None
    components: dict[str, float] = Field(default_factory=dict)
    soft_skill_bonus: float = 0.0
    validation_penalty: float = 0.0
    matched_required_skills: list[str] = Field(default_factory=list)


class Timing(_Strict):
    start_ms: float
    end_ms: float
    duration_ms: float


class UnifiedSkills(_Strict):
    status: AgentStatus
    items: list[SkillItem] = Field(default_factory=list)


class UnifiedExperience(_Strict):
    status: AgentStatus
    total_experience_years: float = 0.0
    entries: list[ExperienceEntry] = Field(default_factory=list)
    overlaps: list[Overlap] = Field(default_factory=list)
    invalid_periods: list[int] = Field(default_factory=list)


class UnifiedSoftSkills(_Strict):
    status: AgentStatus
    items: list[SoftSkillItem] = Field(default_factory=list)
    tone: Optional[ToneProfile] = None
    confidence: float = Field(default=0.0, ge=0, le=1)


class UnifiedAnalysis(_Strict):
    schema_version: Literal["agents-v1"] = SCHEMA_VERSION
    status: Literal["completed", "partial", "failed"]
    skills: UnifiedSkills
    experience: UnifiedExperience
    soft_skills: UnifiedSoftSkills
    conflicts_resolved: list[ConflictResolution] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    matching: Matching
    errors: dict[str, str] = Field(default_factory=dict)
    timings_ms: dict[str, Timing]
