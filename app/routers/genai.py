"""
API تولید سؤال مصاحبه با هوش مصنوعی مولد — قرارداد کامل: docs/genai/API_CONTRACT.md

    POST   /genai/interview-questions                                   درخواست تولید (۲۰۲ — ناهمگام، صف genai)
    GET    /genai/interview-questions?application_id=                   فهرست بانک‌های سؤال یک درخواست شغلی
    GET    /genai/interview-questions/{set_id}                          وضعیت و سؤال‌ها
    PATCH  /genai/interview-questions/{set_id}/questions/{question_id}  بازبینی مصاحبه‌کننده (ویرایش/تأیید)
    GET    /genai/question-bank?skill=&difficulty=&category=            بانک سؤال‌های تأییدشده‌ی مشترک

دسترسی: Admin و HR_Manager همه‌چیز؛ Interviewer فقط بانک سؤال درخواست‌هایی که مصاحبه‌ی آن‌ها با خودش
ثبت شده (و بانک مشترک تأییدشده‌ها)؛ Candidate هیچ‌گاه — کلید پاسخ‌ها نباید به کارجو برسد.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.pagination import CursorParams, cursor_params, paginate_by_cursor
from app.core.queue import enqueue_task
from app.db.session import get_db
from app.genai.prompts import PROMPT_VERSION
from app.genai.service import latest_processed_resume
from app.models import Application, Interview, InterviewQuestion, InterviewQuestionSet, User
from app.schemas.genai import (
    GenerateQuestionsRequest,
    QuestionBankItem,
    QuestionBankResponse,
    QuestionResponse,
    QuestionSetAccepted,
    QuestionSetListResponse,
    QuestionSetResponse,
    QuestionUpdateRequest,
    UsageInfo,
)
from app.tasks.genai import generate_interview_questions_task

router = APIRouter(tags=["GenAI Interview Questions"])

MANAGER_ROLES = ("Admin", "HR_Manager")
REVIEWER_ROLES = ("Admin", "HR_Manager", "Interviewer")
_FORBIDDEN = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="شما اجازه‌ی دسترسی به این بخش را ندارید.")
_SET_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="بانک سؤال پیدا نشد.")


def _ensure_role(user: User, roles: tuple[str, ...]) -> None:
    if user.role not in roles:
        raise _FORBIDDEN


async def _ensure_can_review(db: AsyncSession, user: User, application_id: uuid.UUID) -> None:
    """Interviewer فقط درخواست‌هایی را می‌بیند که مصاحبه‌ی آن‌ها به خودش سپرده شده است."""
    _ensure_role(user, REVIEWER_ROLES)
    if user.role == "Interviewer":
        assigned = await db.execute(
            select(Interview.id).where(Interview.application_id == application_id, Interview.interviewer_id == user.id)
        )
        if assigned.first() is None:
            raise _FORBIDDEN


def _to_response(question_set: InterviewQuestionSet, include_questions: bool = True) -> QuestionSetResponse:
    return QuestionSetResponse(
        id=question_set.id,
        application_id=question_set.application_id,
        job_id=question_set.job_id,
        candidate_id=question_set.candidate_id,
        status=question_set.status,
        language=question_set.language,
        question_count=question_set.question_count,
        difficulty=question_set.difficulty,
        focus_skills=list(question_set.focus_skills or []),
        prompt_version=question_set.prompt_version,
        focus_summary=question_set.focus_summary,
        error=question_set.error,
        usage=UsageInfo(
            prompt_tokens=question_set.prompt_tokens,
            completion_tokens=question_set.completion_tokens,
            latency_ms=question_set.latency_ms,
        ),
        created_at=question_set.created_at,
        completed_at=question_set.completed_at,
        questions=(
            [QuestionResponse.model_validate(item) for item in question_set.questions] if include_questions else []
        ),
    )


async def _load_set(db: AsyncSession, set_id: uuid.UUID) -> InterviewQuestionSet:
    result = await db.execute(
        select(InterviewQuestionSet)
        .options(selectinload(InterviewQuestionSet.questions))
        .where(InterviewQuestionSet.id == set_id)
    )
    question_set = result.scalar_one_or_none()
    if question_set is None:
        raise _SET_NOT_FOUND
    return question_set


@router.post(
    "/interview-questions",
    response_model=QuestionSetAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="درخواست تولید سؤال‌های مصاحبه‌ی اختصاصی برای یک درخواست شغلی (ناهمگام)",
    responses={
        404: {"description": "درخواست شغلی پیدا نشد"},
        409: {"description": "رزومه‌ی کارجو هنوز پردازش نشده"},
        503: {"description": "سرویس هوش مصنوعی مولد پیکربندی نشده یا صف در دسترس نیست"},
    },
)
async def request_question_set(
    payload: GenerateQuestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionSetAccepted:
    """
    یک بانک سؤال با وضعیت pending ثبت و کار تولید به صف genai سپرده می‌شود (پاسخ فوری ۲۰۲)؛ وضعیت با
    GET همان status_url پیگیری می‌شود: pending → processing → completed | failed.
    """
    _ensure_role(current_user, MANAGER_ROLES)
    if not settings.genai_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="سرویس هوش مصنوعی مولد پیکربندی نشده است."
        )

    application = await db.get(Application, payload.application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="درخواست شغلی پیدا نشد.")
    if await latest_processed_resume(db, application.candidate_id, application.tenant_id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="رزومه‌ی این کارجو هنوز تحلیل نشده؛ پس از پایان پردازش رزومه دوباره تلاش کنید.",
        )

    question_set = InterviewQuestionSet(
        application_id=application.id,
        job_id=application.job_id,
        candidate_id=application.candidate_id,
        requested_by=current_user.id,
        status="pending",
        language=payload.language,
        question_count=payload.question_count,
        difficulty=payload.difficulty,
        focus_skills=payload.focus_skills,
        prompt_version=PROMPT_VERSION,
    )
    db.add(question_set)
    await db.commit()

    job_id = await enqueue_task(generate_interview_questions_task, str(question_set.id))
    if job_id is None:
        question_set.status = "failed"
        question_set.error = "افزودن کار به صف ناموفق بود (Redis در دسترس نیست)"
        question_set.completed_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="صف پردازش موقتاً در دسترس نیست.")

    return QuestionSetAccepted(
        id=question_set.id,
        status="pending",
        status_url=f"{settings.API_V1_PREFIX}/genai/interview-questions/{question_set.id}",
    )


@router.get(
    "/interview-questions",
    response_model=QuestionSetListResponse,
    summary="فهرست بانک‌های سؤال یک درخواست شغلی (جدیدترین اول)",
)
async def list_question_sets(
    application_id: uuid.UUID = Query(..., description="شناسه‌ی درخواست شغلی"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: CursorParams = Depends(cursor_params),
) -> QuestionSetListResponse:
    await _ensure_can_review(db, current_user, application_id)
    query = (
        select(InterviewQuestionSet)
        .options(selectinload(InterviewQuestionSet.questions))
        .where(InterviewQuestionSet.application_id == application_id)
    )
    cursor_page = await paginate_by_cursor(
        db, query, sort_column=InterviewQuestionSet.created_at, id_column=InterviewQuestionSet.id, params=page
    )
    return QuestionSetListResponse(
        items=[_to_response(item) for item in cursor_page.items],
        next_cursor=cursor_page.next_cursor,
        previous_cursor=cursor_page.previous_cursor,
        has_next=cursor_page.has_next,
        has_previous=cursor_page.has_previous,
    )


@router.get(
    "/interview-questions/{set_id}",
    response_model=QuestionSetResponse,
    summary="وضعیت و سؤال‌های یک بانک سؤال",
)
async def get_question_set(
    set_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionSetResponse:
    _ensure_role(current_user, REVIEWER_ROLES)
    question_set = await _load_set(db, set_id)
    await _ensure_can_review(db, current_user, question_set.application_id)
    return _to_response(question_set)


@router.patch(
    "/interview-questions/{set_id}/questions/{question_id}",
    response_model=QuestionResponse,
    summary="بازبینی یک سؤال توسط مصاحبه‌کننده: ویرایش متن/کلید پاسخ، تأیید برای بانک سؤال، یادداشت",
)
async def update_question(
    set_id: uuid.UUID,
    question_id: uuid.UUID,
    payload: QuestionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionResponse:
    _ensure_role(current_user, REVIEWER_ROLES)
    question_set = await _load_set(db, set_id)
    await _ensure_can_review(db, current_user, question_set.application_id)
    question = next((item for item in question_set.questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="سؤال در این بانک سؤال پیدا نشد.")

    changes = payload.model_dump(exclude_unset=True)
    for field_name, value in changes.items():
        if field_name in {"question", "expected_answer"} and value is None:
            continue
        setattr(question, field_name, value)
    question.updated_by = current_user.id
    question.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(question)
    return QuestionResponse.model_validate(question)


@router.get(
    "/question-bank",
    response_model=QuestionBankResponse,
    summary="بانک سؤال‌های تأییدشده‌ی مشترک مصاحبه‌کنندگان (جست‌وجو بر اساس مهارت)",
)
async def search_question_bank(
    skill: Optional[str] = Query(default=None, max_length=100, description="نام مهارت (بدون حساسیت به حروف)"),
    difficulty: Optional[str] = Query(default=None, pattern="^(easy|medium|hard)$"),
    category: Optional[str] = Query(default=None, max_length=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: CursorParams = Depends(cursor_params),
) -> QuestionBankResponse:
    """فقط سؤال‌های تأییدشده (is_approved) — ایندکس جزئی ix_interview_questions_approved_skill."""
    _ensure_role(current_user, REVIEWER_ROLES)
    query = (
        select(InterviewQuestion)
        .options(selectinload(InterviewQuestion.question_set))
        .where(InterviewQuestion.is_approved.is_(True))
    )
    if skill:
        query = query.where(func.lower(InterviewQuestion.skill) == skill.strip().lower())
    if difficulty:
        query = query.where(InterviewQuestion.difficulty == difficulty)
    if category:
        query = query.where(InterviewQuestion.category == category)

    cursor_page = await paginate_by_cursor(
        db, query, sort_column=InterviewQuestion.id, id_column=InterviewQuestion.id, params=page
    )
    items = [
        QuestionBankItem(
            **QuestionResponse.model_validate(question).model_dump(),
            question_set_id=question.question_set_id,
            job_id=question.question_set.job_id,
        )
        for question in cursor_page.items
    ]
    return QuestionBankResponse(
        items=items,
        next_cursor=cursor_page.next_cursor,
        previous_cursor=cursor_page.previous_cursor,
        has_next=cursor_page.has_next,
        has_previous=cursor_page.has_previous,
    )
