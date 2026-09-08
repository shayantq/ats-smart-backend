"""
سرویس مدیریت مصاحبه‌ها (Interview Service):
- POST   /api/v1/interviews/                        ساخت جلسه‌ی مصاحبه جدید
- GET    /api/v1/interviews/{id}                       مشاهده‌ی جزئیات یک مصاحبه
- GET    /api/v1/interviews/?...                         لیست مصاحبه‌ها (فیلترپذیر: application_id, date, status)
- PUT    /api/v1/interviews/{id}                           ویرایش (تغییر زمان/مصاحبه‌کننده/لینک)
- PUT    /api/v1/interviews/{id}/evaluation                   ثبت ارزیابی نهایی و نمرات
- DELETE /api/v1/interviews/{id}                                لغو یک مصاحبه

فقط Admin و HR_Manager اجازه‌ی ساخت/ویرایش/لغو مصاحبه دارند. مشاهده و ثبت
ارزیابی برای Admin/HR_Manager و همچنین خودِ مصاحبه‌کننده‌ی تخصیص‌یافته (فقط
مصاحبه‌های خودش) مجاز است.

⚠️ محدودیت شناخته‌شده‌ی مستند (نه یک نقص فراموش‌شده): «ایجاد اتاق مجازی»
فعلاً به‌معنای ثبت یک meeting_link از پیش‌ساخته توسط HR است (مثلاً یک لینک
Google Meet/Zoom که خودش خارج از این سیستم ساخته)، نه یکپارچگی خودکار با
یک API واقعی ویدئوکنفرانس — که خارج از محدوده‌ی این تسک است.
"""

import uuid
from datetime import date as date_type
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.interview_scheduler import cancel_interview_reminder, schedule_interview_reminder
from app.db.session import get_db
from app.models import Application, Candidate, Interview, Job, User
from app.schemas.interviews import (
    InterviewCreateRequest,
    InterviewEvaluationRequest,
    InterviewListResponse,
    InterviewResponse,
    InterviewUpdateRequest,
)

router = APIRouter()

# طبق معیار پذیرش تسک، فقط این نقش‌ها اجازه‌ی زمان‌بندی/ویرایش/لغو مصاحبه دارند
INTERVIEW_MANAGER_ROLES = ("Admin", "HR_Manager")
# نقش‌هایی که مجازند به‌عنوان مصاحبه‌کننده (interviewer_id) تخصیص داده شوند
_VALID_INTERVIEWER_ROLES = ("Interviewer", "HR_Manager")
# نقش‌هایی که اصلاً مجاز به مشاهده‌ی مسیرهای این سرویس‌اند
_INTERVIEW_VIEWER_ROLES = (*INTERVIEW_MANAGER_ROLES, "Interviewer")


async def _get_valid_interviewer(db: AsyncSession, interviewer_id: uuid.UUID) -> User:
    """
    کاربر هدف را می‌خواند و نقشش را اعتبارسنجی می‌کند. اگر کاربر اصلاً وجود
    نداشت -> 404. اگر وجود داشت ولی نقشش Interviewer یا HR_Manager نبود
    (طبق معیار پذیرش اصلی این تسک) -> 422 (خطای اعتبارسنجی).
    """
    result = await db.execute(select(User).where(User.id == interviewer_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="کاربر مصاحبه‌کننده یافت نشد.")

    if user.role not in _VALID_INTERVIEWER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="این کاربر نقش مصاحبه‌کننده (Interviewer) یا کارشناس HR ندارد و نمی‌تواند به یک مصاحبه تخصیص یابد.",
        )

    return user


async def _get_candidate_contact(db: AsyncSession, application: Application) -> tuple[str, str]:
    """ایمیل و نام کامل کارجوی صاحب یک درخواست را برمی‌گرداند (برای یادآور مصاحبه)."""
    candidate_result = await db.execute(select(Candidate).where(Candidate.id == application.candidate_id))
    candidate = candidate_result.scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="پروفایل کارجوی این درخواست یافت نشد.")

    user_result = await db.execute(select(User).where(User.id == candidate.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="کاربر متناظر کارجو یافت نشد.")

    candidate_name = f"{candidate.first_name} {candidate.last_name}".strip() or user.email
    return user.email, candidate_name


async def _build_interview_response(db: AsyncSession, interview: Interview) -> InterviewResponse:
    """
    پاسخ کامل یک مصاحبه را می‌سازد — شامل نام مصاحبه‌کننده، نام کارجو، و عنوان
    آگهی (با join از طریق Application) تا جدول‌های داشبورد بدون درخواست‌های
    اضافی، اطلاعات لازم برای نمایش را داشته باشند.
    """
    interviewer_result = await db.execute(select(User).where(User.id == interview.interviewer_id))
    interviewer = interviewer_result.scalar_one_or_none()

    application_result = await db.execute(
        select(Job.title, Candidate.first_name, Candidate.last_name)
        .select_from(Application)
        .join(Job, Job.id == Application.job_id)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .where(Application.id == interview.application_id)
    )
    row = application_result.first()

    job_title = row.title if row is not None else ""
    candidate_name = f"{row.first_name} {row.last_name}".strip() if row is not None else ""

    return InterviewResponse(
        interview_id=interview.id,
        application_id=interview.application_id,
        interviewer_id=interview.interviewer_id,
        interviewer_name=interviewer.email if interviewer else "",
        candidate_name=candidate_name,
        job_title=job_title,
        scheduled_at=interview.scheduled_at,
        meeting_link=interview.meeting_link,
        status=interview.status,
        evaluation_scores=interview.evaluation_scores,
        overall_score=interview.overall_score,
        feedback_text=interview.feedback_text,
        evaluated_at=interview.evaluated_at,
    )


@router.post(
    "/",
    response_model=InterviewResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Interviews"],
    summary="ساخت جلسه‌ی مصاحبه‌ی جدید",
    dependencies=[Depends(require_roles(*INTERVIEW_MANAGER_ROLES))],
)
async def create_interview(
    payload: InterviewCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> InterviewResponse:
    """
    ترتیب پردازش:
    ۱. اطمینان از وجود درخواست (Application) با application_id ارسالی -> در غیر این صورت 404.
    ۲. اعتبارسنجی نقش مصاحبه‌کننده (باید Interviewer یا HR_Manager باشد) -> در غیر این صورت 422.
    ۳. ساخت ردیف Interview با وضعیت پیش‌فرض Pending و ثبت در دیتابیس -> 201 Created.
    ۴. زمان‌بندی یادآور ایمیل برای هر دو نفر (کارجو و مصاحبه‌کننده)، دقیقاً
       ۲۴ ساعت پیش از scheduled_at (بنگرید app/core/interview_scheduler.py).
    """
    application_result = await db.execute(select(Application).where(Application.id == payload.application_id))
    application = application_result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="درخواست موردنظر یافت نشد.")

    interviewer = await _get_valid_interviewer(db, payload.interviewer_id)

    interview = Interview(
        application_id=payload.application_id,
        interviewer_id=payload.interviewer_id,
        scheduled_at=payload.scheduled_at,
        meeting_link=payload.meeting_link,
    )
    db.add(interview)
    await db.flush()  # برای این‌که interview.id پیش از commit نهایی در دسترس باشد

    candidate_email, candidate_name = await _get_candidate_contact(db, application)

    reminder_job_ids = schedule_interview_reminder(
        interview_id=str(interview.id),
        scheduled_at=payload.scheduled_at,
        candidate_email=candidate_email,
        candidate_name=candidate_name,
        interviewer_email=interviewer.email,
        interviewer_name=interviewer.email,
        meeting_link=payload.meeting_link,
    )
    interview.reminder_job_ids = reminder_job_ids or None

    await db.commit()
    await db.refresh(interview)

    return await _build_interview_response(db, interview)


@router.get(
    "/{interview_id}",
    response_model=InterviewResponse,
    status_code=status.HTTP_200_OK,
    tags=["Interviews"],
    summary="مشاهده‌ی جزئیات یک مصاحبه",
)
async def get_interview(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewResponse:
    """قابل‌مشاهده برای Admin/HR_Manager، یا خودِ مصاحبه‌کننده‌ی تخصیص‌یافته به این مصاحبه."""
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="مصاحبه موردنظر یافت نشد.")

    is_manager = current_user.role in INTERVIEW_MANAGER_ROLES
    is_assigned_interviewer = current_user.id == interview.interviewer_id
    if not (is_manager or is_assigned_interviewer):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="شما اجازه‌ی مشاهده‌ی این مصاحبه را ندارید.")

    return await _build_interview_response(db, interview)


@router.get(
    "/",
    response_model=InterviewListResponse,
    status_code=status.HTTP_200_OK,
    tags=["Interviews"],
    summary="لیست مصاحبه‌ها (فیلترپذیر بر اساس درخواست/تاریخ/وضعیت)",
)
async def list_interviews(
    application_id: uuid.UUID | None = Query(default=None, description="فیلتر بر اساس یک درخواست خاص"),
    day: date_type | None = Query(default=None, alias="date", description="فیلتر بر اساس روز برگزاری (YYYY-MM-DD)"),
    evaluation_status: str | None = Query(
        default=None, alias="status", description="فیلتر بر اساس وضعیت فرم ارزیابی: Pending یا Completed"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewListResponse:
    """
    Admin/HR_Manager بدون محدودیت (برای «لیست مصاحبه‌های روزانه» در داشبورد)؛
    Interviewer فقط مصاحبه‌های خودش را می‌بیند (صرف‌نظر از پارامترهای ارسالی) —
    تا کسی نتواند لیست مصاحبه‌های سایر مصاحبه‌کنندگان را ببیند.
    """
    if current_user.role not in _INTERVIEW_VIEWER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="شما اجازه‌ی دسترسی به این بخش را ندارید.")

    query = select(Interview)

    if application_id is not None:
        query = query.where(Interview.application_id == application_id)
    if day is not None:
        query = query.where(func.date(Interview.scheduled_at) == day)
    if evaluation_status is not None:
        query = query.where(Interview.status == evaluation_status)
    if current_user.role == "Interviewer":
        query = query.where(Interview.interviewer_id == current_user.id)

    query = query.order_by(Interview.scheduled_at.asc())
    result = await db.execute(query)
    interviews = result.scalars().all()

    items = [await _build_interview_response(db, interview) for interview in interviews]

    return InterviewListResponse(total=len(items), items=items)


@router.put(
    "/{interview_id}",
    response_model=InterviewResponse,
    status_code=status.HTTP_200_OK,
    tags=["Interviews"],
    summary="ویرایش یک مصاحبه (تغییر زمان/مصاحبه‌کننده/لینک)",
    dependencies=[Depends(require_roles(*INTERVIEW_MANAGER_ROLES))],
)
async def update_interview(
    interview_id: uuid.UUID,
    payload: InterviewUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> InterviewResponse:
    """
    اگر interviewer_id تغییر کند، دوباره اعتبارسنجی نقش انجام می‌شود. اگر
    scheduled_at یا interviewer_id تغییر کند، یادآورهای قبلی لغو و یادآورهای
    جدید (طبق زمان/گیرندگان به‌روزشده) زمان‌بندی می‌شوند.
    """
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="مصاحبه موردنظر یافت نشد.")

    update_data = payload.model_dump(exclude_unset=True)

    interviewer: User | None = None
    if "interviewer_id" in update_data:
        interviewer = await _get_valid_interviewer(db, update_data["interviewer_id"])

    for field_name, value in update_data.items():
        setattr(interview, field_name, value)

    needs_reschedule = "scheduled_at" in update_data or "interviewer_id" in update_data
    if needs_reschedule:
        cancel_interview_reminder(interview.reminder_job_ids)

        application_result = await db.execute(select(Application).where(Application.id == interview.application_id))
        application = application_result.scalar_one_or_none()
        if application is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="درخواست مرتبط با این مصاحبه یافت نشد.")

        candidate_email, candidate_name = await _get_candidate_contact(db, application)

        if interviewer is None:
            interviewer_result = await db.execute(select(User).where(User.id == interview.interviewer_id))
            interviewer = interviewer_result.scalar_one_or_none()

        new_job_ids = schedule_interview_reminder(
            interview_id=str(interview.id),
            scheduled_at=interview.scheduled_at,
            candidate_email=candidate_email,
            candidate_name=candidate_name,
            interviewer_email=interviewer.email if interviewer else "",
            interviewer_name=interviewer.email if interviewer else "",
            meeting_link=interview.meeting_link or "",
        )
        interview.reminder_job_ids = new_job_ids or None

    db.add(interview)
    await db.commit()
    await db.refresh(interview)

    return await _build_interview_response(db, interview)


@router.put(
    "/{interview_id}/evaluation",
    response_model=InterviewResponse,
    status_code=status.HTTP_200_OK,
    tags=["Interviews"],
    summary="ثبت ارزیابی نهایی و نمرات یک مصاحبه",
)
async def submit_interview_evaluation(
    interview_id: uuid.UUID,
    payload: InterviewEvaluationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewResponse:
    """
    فقط خودِ مصاحبه‌کننده‌ی تخصیص‌یافته به این مصاحبه (یا Admin/HR_Manager برای
    ثبت جایگزین) می‌تواند نمره ثبت کند. میانگین evaluation_scores به‌عنوان
    overall_score محاسبه می‌شود (نه این‌که کلاینت آن را مستقیم بفرستد) تا
    همیشه با نمرات واقعی هم‌خوان بماند. بعد از ثبت موفق، status به Completed
    تغییر می‌کند — طبق معیار پذیرش تسک.
    """
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="مصاحبه موردنظر یافت نشد.")

    is_manager = current_user.role in INTERVIEW_MANAGER_ROLES
    is_assigned_interviewer = current_user.id == interview.interviewer_id
    if not (is_manager or is_assigned_interviewer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="شما اجازه‌ی ثبت ارزیابی برای این مصاحبه را ندارید."
        )

    overall_score = sum(payload.evaluation_scores.values()) / len(payload.evaluation_scores)

    interview.evaluation_scores = payload.evaluation_scores
    interview.overall_score = round(overall_score, 2)
    interview.feedback_text = payload.feedback_text
    interview.status = "Completed"
    interview.evaluated_at = datetime.now(timezone.utc)

    db.add(interview)
    await db.commit()
    await db.refresh(interview)

    return await _build_interview_response(db, interview)


@router.delete(
    "/{interview_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Interviews"],
    summary="لغو (حذف) یک مصاحبه",
    dependencies=[Depends(require_roles(*INTERVIEW_MANAGER_ROLES))],
)
async def delete_interview(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """مصاحبه را حذف و هر یادآور زمان‌بندی‌شده‌ی مربوط به آن را نیز لغو می‌کند."""
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="مصاحبه موردنظر یافت نشد.")

    cancel_interview_reminder(interview.reminder_job_ids)

    await db.delete(interview)
    await db.commit()
