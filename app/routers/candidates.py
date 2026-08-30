"""
میکروسرویس پورتال اختصاصی کارجو (Candidate Dashboard):
- GET/PUT /api/v1/candidates/me                          مشاهده/ویرایش پروفایل شخصی و تگ‌های مهارتی
- GET     /api/v1/candidates/me/applications               سیستم رهگیر وضعیت (کدام آگهی، کدام مرحله)
- GET     /api/v1/candidates/me/offers                      صندوق ورودی پیشنهادهای شغلی فعال
- PUT     /api/v1/candidates/me/applications/{id}/respond    پاسخ کارجو به یک پیشنهاد (قبول/رد)

همه‌ی مسیرها فقط برای نقش Candidate هستند و همیشه روی «پروفایل/درخواست‌های
خودِ کاربر لاگین‌شده» عمل می‌کنند — هیچ‌جا candidate_id از ورودی کاربر گرفته
نمی‌شود تا امکان دسترسی به اطلاعات سایر کارجویان وجود نداشته باشد.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.candidate_utils import get_or_create_candidate_profile
from app.core.deps import get_current_user, require_roles
from app.core.state_machine import ApplicationStatus, is_transition_allowed
from app.db.session import get_db
from app.models import Application, Company, Job, StatusHistory, User
from app.schemas.candidates import (
    ApplicationTrackerItem,
    ApplicationTrackerResponse,
    CandidateProfileResponse,
    CandidateProfileUpdateRequest,
    OfferInboxItem,
    OfferInboxResponse,
    OfferResponseRequest,
    OfferResponseResult,
)

router = APIRouter(dependencies=[Depends(require_roles("Candidate"))])


@router.get(
    "/me",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="مشاهده‌ی پروفایل شخصی کارجوی لاگین‌شده",
)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CandidateProfileResponse:
    candidate = await get_or_create_candidate_profile(db, current_user)
    await db.commit()

    return CandidateProfileResponse(
        id=candidate.id,
        email=current_user.email,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        phone=candidate.phone,
        location=candidate.location,
        skills=candidate.skills or [],
    )


@router.put(
    "/me",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="ویرایش پروفایل شخصی و تگ‌های مهارتی (Partial Update)",
)
async def update_my_profile(
    payload: CandidateProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CandidateProfileResponse:
    candidate = await get_or_create_candidate_profile(db, current_user)

    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(candidate, field_name, value)

    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    return CandidateProfileResponse(
        id=candidate.id,
        email=current_user.email,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        phone=candidate.phone,
        location=candidate.location,
        skills=candidate.skills or [],
    )


@router.get(
    "/me/applications",
    response_model=ApplicationTrackerResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="سیستم رهگیر وضعیت — رزومه‌ی کارجو برای هر آگهی در کدام مرحله است",
)
async def list_my_applications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationTrackerResponse:
    candidate = await get_or_create_candidate_profile(db, current_user)
    await db.commit()

    query = (
        select(Application.id, Application.job_id, Job.title, Application.current_status, Application.updated_at)
        .join(Job, Job.id == Application.job_id)
        .where(Application.candidate_id == candidate.id)
        .order_by(Application.updated_at.desc())
    )
    result = await db.execute(query)
    rows = result.all()

    items = [
        ApplicationTrackerItem(
            application_id=row.id,
            job_id=row.job_id,
            job_title=row.title,
            current_status=row.current_status,
            updated_at=row.updated_at,
        )
        for row in rows
    ]

    return ApplicationTrackerResponse(total=len(items), items=items)


@router.get(
    "/me/offers",
    response_model=OfferInboxResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="صندوق ورودی پیشنهادهای شغلی فعال (درخواست‌هایی با وضعیت Offer)",
)
async def list_my_offers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OfferInboxResponse:
    candidate = await get_or_create_candidate_profile(db, current_user)
    await db.commit()

    query = (
        select(Application.id, Application.job_id, Job.title, Company.name, Application.updated_at)
        .join(Job, Job.id == Application.job_id)
        .outerjoin(Company, Company.id == Job.company_id)
        .where(
            Application.candidate_id == candidate.id,
            Application.current_status == ApplicationStatus.OFFER.value,
        )
        .order_by(Application.updated_at.desc())
    )
    result = await db.execute(query)
    rows = result.all()

    items = [
        OfferInboxItem(
            application_id=row.id,
            job_id=row.job_id,
            job_title=row.title,
            company_name=row.name,
            updated_at=row.updated_at,
        )
        for row in rows
    ]

    return OfferInboxResponse(total=len(items), items=items)


@router.put(
    "/me/applications/{application_id}/respond",
    response_model=OfferResponseResult,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="پاسخ کارجو به یک پیشنهاد شغلی فعال (قبول یا رد)",
)
async def respond_to_offer(
    application_id: uuid.UUID,
    payload: OfferResponseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OfferResponseResult:
    """
    فقط روی درخواست‌های خودِ کارجوی لاگین‌شده و فقط وقتی current_status
    دقیقاً «Offer» باشد قابل استفاده است. تصمیم «قبول» به Accepted و
    تصمیم «رد» به Rejected تبدیل می‌شود — این دقیقاً همان دو مسیر مجاز
    ماشین وضعیت از Offer هستند (بنگرید app/core/state_machine.py)، پس
    هیچ پرش غیرمجازی از این طریق ممکن نیست.
    """
    candidate = await get_or_create_candidate_profile(db, current_user)

    result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.candidate_id == candidate.id,
        )
    )
    application = result.scalar_one_or_none()

    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="این درخواست یافت نشد.")

    if application.current_status != ApplicationStatus.OFFER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="این درخواست در حال حاضر پیشنهاد شغلی فعالی برای پاسخ‌دادن ندارد.",
        )

    new_status = (
        ApplicationStatus.ACCEPTED.value if payload.decision == "accept" else ApplicationStatus.REJECTED.value
    )

    # بررسی دفاعی: طبق ماشین وضعیت، از Offer فقط Accepted/Rejected مجازند —
    # این شرط عملاً همیشه True است، ولی برای هم‌خوانی با گاردریل مرکزی نگه داشته شده.
    if not is_transition_allowed(application.current_status, new_status):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business Logic Violation")

    previous_status = application.current_status
    application.current_status = new_status
    db.add(application)

    history_entry = StatusHistory(
        application_id=application.id,
        old_status=previous_status,
        new_status=new_status,
        changed_by=current_user.id,
    )
    db.add(history_entry)

    await db.commit()

    message = (
        "پیشنهاد شغلی با موفقیت پذیرفته شد."
        if payload.decision == "accept"
        else "پیشنهاد شغلی رد شد."
    )

    return OfferResponseResult(application_id=application.id, new_status=new_status, message=message)
