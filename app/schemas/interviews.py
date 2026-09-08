"""
اسکیمای ورودی و خروجی سرویس مدیریت مصاحبه‌ها (Interview Service):
- POST   /api/v1/interviews/                        ساخت جلسه‌ی مصاحبه جدید
- GET    /api/v1/interviews/{id}                       مشاهده‌ی جزئیات یک مصاحبه
- GET    /api/v1/interviews/?...                         لیست مصاحبه‌ها (فیلترپذیر)
- PUT    /api/v1/interviews/{id}                           ویرایش (زمان/مصاحبه‌کننده/لینک)
- PUT    /api/v1/interviews/{id}/evaluation                   ثبت ارزیابی و نمرات
- DELETE /api/v1/interviews/{id}                                لغو یک مصاحبه
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import strip_html_tags

# معیارهای نمره‌دهی مجاز فرم ارزیابی — یک مجموعه‌ی ثابت و شناخته‌شده، تا هم
# فرانت‌اند بداند دقیقاً چه فیلدهایی رندر کند و هم نمرات قابل مقایسه بمانند.
ALLOWED_EVALUATION_CRITERIA = frozenset({"technical_skill", "problem_solving", "communication", "culture_fit"})
_MIN_SCORE = 1
_MAX_SCORE = 10


class InterviewCreateRequest(BaseModel):
    """بدنه‌ی درخواست ساخت مصاحبه‌ی جدید."""

    application_id: uuid.UUID
    interviewer_id: uuid.UUID
    scheduled_at: datetime
    meeting_link: str = Field(min_length=1, max_length=500)

    @field_validator("meeting_link", mode="before")
    @classmethod
    def sanitize_meeting_link(cls, value: str) -> str:
        if isinstance(value, str):
            return strip_html_tags(value)
        return value

    @field_validator("scheduled_at")
    @classmethod
    def normalize_timezone(cls, value: datetime) -> datetime:
        """اگر کلاینت تاریخ را بدون Timezone بفرستد، به‌صورت UTC در نظر گرفته می‌شود."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class InterviewUpdateRequest(BaseModel):
    """بدنه‌ی ویرایش مصاحبه — هر فیلد اختیاری است (Partial Update)."""

    interviewer_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[datetime] = None
    meeting_link: Optional[str] = Field(default=None, min_length=1, max_length=500)

    @field_validator("meeting_link", mode="before")
    @classmethod
    def sanitize_meeting_link(cls, value):
        if isinstance(value, str):
            return strip_html_tags(value)
        return value

    @field_validator("scheduled_at")
    @classmethod
    def normalize_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class InterviewEvaluationRequest(BaseModel):
    """
    بدنه‌ی ثبت ارزیابی نهایی — فقط توسط مصاحبه‌کننده‌ی تخصیص‌یافته (یا
    Admin/HR_Manager) و فقط یک‌بار برای هر مصاحبه معنا دارد (ثبت دوباره،
    مقادیر قبلی را جایگزین می‌کند).
    """

    evaluation_scores: dict[str, int] = Field(
        description=f"نگاشت هر معیار (از میان {sorted(ALLOWED_EVALUATION_CRITERIA)}) به نمره‌ی {_MIN_SCORE} تا {_MAX_SCORE}"
    )
    feedback_text: str = Field(min_length=1, max_length=4000)

    @field_validator("evaluation_scores")
    @classmethod
    def validate_scores(cls, value: dict[str, int]) -> dict[str, int]:
        if not value:
            raise ValueError("حداقل یک معیار نمره‌دهی باید ارسال شود.")

        unknown_criteria = set(value.keys()) - ALLOWED_EVALUATION_CRITERIA
        if unknown_criteria:
            raise ValueError(
                f"معیار(های) ناشناخته: {sorted(unknown_criteria)}. معیارهای مجاز: {sorted(ALLOWED_EVALUATION_CRITERIA)}"
            )

        for criterion, score in value.items():
            if not (_MIN_SCORE <= score <= _MAX_SCORE):
                raise ValueError(f"نمره‌ی «{criterion}» باید بین {_MIN_SCORE} تا {_MAX_SCORE} باشد.")

        return value

    @field_validator("feedback_text", mode="before")
    @classmethod
    def sanitize_feedback(cls, value: str) -> str:
        if isinstance(value, str):
            return strip_html_tags(value)
        return value


class InterviewResponse(BaseModel):
    """ساختار خروجی یک مصاحبه — شامل خلاصه‌ی وضعیت ارزیابی برای نمایش در جدول‌های داشبورد."""

    interview_id: uuid.UUID
    application_id: uuid.UUID
    interviewer_id: uuid.UUID
    interviewer_name: str
    candidate_name: str = ""
    job_title: str = ""
    scheduled_at: Optional[datetime] = None
    meeting_link: Optional[str] = None
    status: str = "Pending"
    evaluation_scores: Optional[dict[str, int]] = None
    overall_score: Optional[float] = None
    feedback_text: Optional[str] = None
    evaluated_at: Optional[datetime] = None


class InterviewListResponse(BaseModel):
    total: int
    items: list[InterviewResponse]
