"""
اسکیماهای سرویس تولید سؤال مصاحبه با هوش مصنوعی مولد (app/genai، app/routers/genai.py).

دو گروه:
  ۱. قرارداد خروجی مدل زبانی (GeneratedQuestionSet) — همین مدل‌ها به JSON Schema تبدیل و در درخواست به
     سرویس مدل زبانی فرستاده می‌شوند (خروجی مقید)، و پاسخ با همان‌ها اعتبارسنجی می‌شود. نسخه‌ی خروجی
     در docs/genai/interview-question-set.schema.json (بنگرید app/genai/contract.py).
  ۲. قرارداد API سمت کاربران پلتفرم (درخواست/پاسخ endpoint های /api/v1/genai).

قواعد JSON Schema برای سازگاری با خروجی مقید «strict» اکثر سرویس‌ها: همه‌ی فیلدها اجباری، هیچ فیلد
اضافه‌ای مجاز نیست (additionalProperties: false)، بدون مقدار پیش‌فرض.
"""

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.sanitize import strip_html_tags

QuestionCategory = Literal["technical", "problem_solving", "system_design", "behavioral", "gap_probe"]
QuestionDifficulty = Literal["easy", "medium", "hard"]
QuestionSetStatus = Literal["pending", "processing", "completed", "failed"]

MIN_QUESTIONS = 3
MAX_QUESTIONS = 15


# ---------------------------------------------------------------------------
# ۱. خروجی ساخت‌یافته‌ی مدل زبانی
# ---------------------------------------------------------------------------
class GeneratedQuestion(BaseModel):
    """یک سؤال مصاحبه‌ی تخصصی به همراه کلید پاسخ برای مصاحبه‌کننده."""

    model_config = ConfigDict(extra="forbid")

    category: QuestionCategory = Field(
        description="technical: دانش فنی · problem_solving: حل مسئله · system_design: طراحی سیستم · "
        "behavioral: رفتاری/تجربه · gap_probe: سنجش یک نقطه‌ی ضعف یا مهارت گم‌شده"
    )
    skill: str = Field(min_length=1, max_length=100, description="مهارت اصلی که سؤال می‌سنجد")
    difficulty: QuestionDifficulty
    question: str = Field(min_length=10, max_length=1200, description="متن سؤال، خطاب به کارجو")
    purpose: str = Field(
        min_length=5,
        max_length=600,
        description="چرا این سؤال برای این کارجو — ارجاع به نقطه‌ی قوت یا ضعف مشخص پروفایل",
    )
    expected_answer: str = Field(min_length=10, max_length=2500, description="کلید پاسخ: پاسخ مورد انتظار")
    evaluation_points: list[str] = Field(
        min_length=1, max_length=6, description="نکاتی که پاسخ خوب باید پوشش دهد (معیار نمره‌دهی)"
    )
    red_flags: list[str] = Field(max_length=4, description="نشانه‌های پاسخ ضعیف یا نادرست")
    follow_ups: list[str] = Field(max_length=3, description="سؤال‌های پیگیری برای عمیق‌تر کردن بحث")
    estimated_minutes: int = Field(ge=1, le=30, description="زمان تقریبی پاسخ در مصاحبه")


class GeneratedQuestionSet(BaseModel):
    """خروجی کامل یک درخواست تولید سؤال — دقیقاً همان JSON که مدل زبانی باید برگرداند."""

    model_config = ConfigDict(extra="forbid")

    focus_summary: str = Field(
        min_length=10, max_length=1500, description="خلاصه‌ی محورهای مصاحبه برای این کارجو و این آگهی"
    )
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=MAX_QUESTIONS)


# ---------------------------------------------------------------------------
# ۲. قرارداد API پلتفرم
# ---------------------------------------------------------------------------
class GenerateQuestionsRequest(BaseModel):
    """درخواست تولید بانک سؤال برای یک درخواست شغلی (کارجو × آگهی)."""

    model_config = ConfigDict(extra="forbid")

    application_id: uuid.UUID
    question_count: int = Field(default=8, ge=MIN_QUESTIONS, le=MAX_QUESTIONS)
    difficulty: Literal["mixed", "easy", "medium", "hard"] = "mixed"
    focus_skills: list[str] = Field(
        default_factory=list, max_length=10, description="مهارت‌هایی که باید حتماً سنجیده شوند"
    )
    language: Literal["fa", "en"] = "fa"

    @field_validator("focus_skills")
    @classmethod
    def clean_focus_skills(cls, skills: list[str]) -> list[str]:
        cleaned = [strip_html_tags(skill).strip()[:100] for skill in skills]
        return [skill for skill in dict.fromkeys(cleaned) if skill]


class QuestionResponse(BaseModel):
    """یک سؤال ذخیره‌شده در بانک سؤال (خروجی مدل + بازبینی مصاحبه‌کننده)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    category: str
    skill: str
    difficulty: str
    question: str
    purpose: str
    expected_answer: str
    evaluation_points: list[str]
    red_flags: list[str]
    follow_ups: list[str]
    estimated_minutes: int
    is_approved: bool
    interviewer_notes: Optional[str] = None
    updated_at: Optional[datetime] = None


class UsageInfo(BaseModel):
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: Optional[int] = None


class QuestionSetResponse(BaseModel):
    """وضعیت و محتوای یک بانک سؤال؛ تا status=completed فهرست questions خالی است."""

    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    status: QuestionSetStatus
    language: str
    question_count: int
    difficulty: str
    focus_skills: list[str]
    prompt_version: str
    focus_summary: Optional[str] = None
    error: Optional[str] = None
    usage: UsageInfo
    created_at: datetime
    completed_at: Optional[datetime] = None
    questions: list[QuestionResponse] = Field(default_factory=list)


class QuestionSetAccepted(BaseModel):
    """پاسخ 202: درخواست ثبت و در صف پردازش قرار گرفت."""

    id: uuid.UUID
    status: QuestionSetStatus
    status_url: str


class QuestionSetListResponse(BaseModel):
    items: list[QuestionSetResponse]
    next_cursor: Optional[str] = None
    previous_cursor: Optional[str] = None
    has_next: bool = False
    has_previous: bool = False


class QuestionUpdateRequest(BaseModel):
    """بازبینی مصاحبه‌کننده: ویرایش متن/کلید پاسخ، تأیید برای بانک سؤال، یادداشت."""

    model_config = ConfigDict(extra="forbid")

    question: Optional[str] = Field(default=None, min_length=10, max_length=1200)
    expected_answer: Optional[str] = Field(default=None, min_length=10, max_length=2500)
    is_approved: Optional[bool] = None
    interviewer_notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("question", "expected_answer", "interviewer_notes")
    @classmethod
    def sanitize(cls, value: Optional[str]) -> Optional[str]:
        return strip_html_tags(value).strip() if value is not None else None


class QuestionBankItem(QuestionResponse):
    """سؤال تأییدشده در بانک سؤال مشترک مصاحبه‌کنندگان (قابل جست‌وجو بر اساس مهارت)."""

    question_set_id: uuid.UUID
    job_id: uuid.UUID


class QuestionBankResponse(BaseModel):
    items: list[QuestionBankItem]
    next_cursor: Optional[str] = None
    previous_cursor: Optional[str] = None
    has_next: bool = False
    has_previous: bool = False
