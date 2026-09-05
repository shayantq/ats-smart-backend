"""
سرویس مدیریت مصاحبه‌ها (Interview Service):
- POST   /api/v1/interviews/                        ساخت جلسه‌ی مصاحبه جدید
- GET    /api/v1/interviews/{id}                       مشاهده‌ی جزئیات یک مصاحبه
- GET    /api/v1/interviews/?application_id=...          لیست مصاحبه‌های یک درخواست خاص
- PUT    /api/v1/interviews/{id}                           ویرایش (تغییر زمان/مصاحبه‌کننده/لینک)
- DELETE /api/v1/interviews/{id}                             لغو یک مصاحبه

فقط Admin و HR_Manager اجازه‌ی ساخت/ویرایش/لغو مصاحبه دارند. مشاهده برای
Admin/HR_Manager و همچنین خودِ مصاحبه‌کننده‌ی تخصیص‌یافته (فقط مصاحبه‌های
خودش) مجاز است.

⚠️ محدودیت شناخته‌شده‌ی مستند (نه یک نقص فراموش‌شده): «ایجاد اتاق مجازی»
فعلاً به‌معنای ثبت یک meeting_link از پیش‌ساخته توسط HR است (مثلاً یک لینک
Google Meet/Zoom که خودش خارج از این سیستم ساخته)، نه یکپارچگی خودکار با
یک API واقعی ویدئوکنفرانس — که خارج از محدوده‌ی این تسک است.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.interview_scheduler import cancel_interview_reminder, schedule_interview_reminder
from app.db.session import get_db
from app.models import Application, Candidate, Interview, User
from app.schemas.interviews import (
    InterviewCreateRequest,
    InterviewListResponse,
    InterviewResponse,
    InterviewUpdateRequest,
)

router = APIRouter()

# طبق معیار پذیرش تسک، فقط این نقش‌ها اجازه‌ی زمان‌بندی/ویرایش/لغو مصاحبه دارند
INTERVIEW_MANAGER_ROLES = ("Admin", "HR_Manager")
# نقش‌هایی که مجازند به‌عنوان مصاحبه‌کننده (interviewer_id) تخصیص داده شوند
_VALID_INTERVIEWER_ROLES = ("Interviewer", "HR_Manager")


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


def _build_interview_response(interview: Interview, interviewer_name: str) -> InterviewResponse:
    return InterviewResponse(
        interview_id=interview.id,
        application_id=interview.application_id,
        interviewer_id=interview.interviewer_id,
        interviewer_name=interviewer_name,
        scheduled_at=interview.scheduled_at,
        meeting_link=interview.meeting_link,
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
    ۳. ساخت ردیف Interview و ثبت در دیتابیس -> 201 Created.
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

    return _build_interview_response(interview, interviewer_name=interviewer.email)


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

    interviewer_result = await db.execute(select(User).where(User.id == interview.interviewer_id))
    interviewer = interviewer_result.scalar_one_or_none()

    return _build_interview_response(interview, interviewer_name=interviewer.email if interviewer else "")


@router.get(
    "/",
    response_model=InterviewListResponse,
    status_code=status.HTTP_200_OK,
    tags=["Interviews"],
    summary="لیست مصاحبه‌های یک درخواست خاص",
    dependencies=[Depends(require_roles(*INTERVIEW_MANAGER_ROLES))],
)
async def list_interviews(
    application_id: uuid.UUID = Query(..., description="شناسه‌ی درخواست موردنظر"),
    db: AsyncSession = Depends(get_db),
) -> InterviewListResponse:
    """فقط Admin/HR_Manager — لیست همه‌ی مصاحبه‌های زمان‌بندی‌شده برای یک درخواست خاص."""
    query = (
        select(Interview, User.email)
        .join(User, User.id == Interview.interviewer_id)
        .where(Interview.application_id == application_id)
        .order_by(Interview.scheduled_at.asc())
    )
    result = await db.execute(query)
    rows = result.all()

    items = [_build_interview_response(interview, interviewer_name=email) for interview, email in rows]

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

    if interviewer is None:
        interviewer_result = await db.execute(select(User).where(User.id == interview.interviewer_id))
        interviewer = interviewer_result.scalar_one_or_none()

    return _build_interview_response(interview, interviewer_name=interviewer.email if interviewer else "")


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
