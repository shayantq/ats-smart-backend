"""
میکروسرویس پورتال اختصاصی کارجو (Candidate Dashboard) + موتور جستجوی
پیشرفته‌ی کارجویان برای تیم منابع انسانی:
- GET/PUT /api/v1/candidates/me                          مشاهده/ویرایش پروفایل شخصی و تگ‌های مهارتی
- GET     /api/v1/candidates/me/applications               سیستم رهگیر وضعیت (کدام آگهی، کدام مرحله)
- GET     /api/v1/candidates/me/offers                      صندوق ورودی پیشنهادهای شغلی فعال
- PUT     /api/v1/candidates/me/applications/{id}/respond    پاسخ کارجو به یک پیشنهاد (قبول/رد)
- GET     /api/v1/candidates/search/                       جستجوی ترکیبی متنی + فیلترهای ساختاریافته (فقط HR/Admin)

مسیرهای بخش «پورتال کارجو» فقط برای نقش Candidate هستند و همیشه روی
«پروفایل/درخواست‌های خودِ کاربر لاگین‌شده» عمل می‌کنند — هیچ‌جا candidate_id
از ورودی کاربر گرفته نمی‌شود تا امکان دسترسی به اطلاعات سایر کارجویان وجود
نداشته باشد. مسیر جستجو برعکس این قاعده، مخصوص نقش‌های HR است، پس (بر خلاف
نسخه‌ی قبلی این فایل) دیگر یک dependency واحد روی کل APIRouter تعریف نشده؛
هر مسیر جداگانه نقش مجاز خودش را با dependencies=[Depends(require_roles(...))]
مشخص می‌کند — دقیقاً همان الگویی که در app/routers/jobs.py و
app/routers/applications.py استفاده شده است.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.candidate_utils import get_or_create_candidate_profile
from app.core.deps import get_current_user, require_roles
from app.core.pagination import CursorParams, cursor_params, paginate_by_cursor
from app.core.search_query import build_resume_search_tsquery, resume_fts_tsvector_expression
from app.core.state_machine import ApplicationStatus, is_transition_allowed
from app.db.session import get_db
from app.models import Application, Candidate, Company, Job, Resume, StatusHistory, User
from app.schemas.candidate_search import CandidateSearchItem, CandidateSearchResponse
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

router = APIRouter()

# طبق معیار پذیرش تسک، جستجوی پیشرفته‌ی کارجویان فقط برای تیم منابع انسانی
# (نه خودِ کارجوها) در دسترس است — همان دو نقش مجاز مدیریت آگهی/بورد کانبان.
CANDIDATE_SEARCH_ROLES = ("Admin", "HR_Manager")


@router.get(
    "/me",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="مشاهده‌ی پروفایل شخصی کارجوی لاگین‌شده",
    dependencies=[Depends(require_roles("Candidate"))],
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
    dependencies=[Depends(require_roles("Candidate"))],
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
    dependencies=[Depends(require_roles("Candidate"))],
)
async def list_my_applications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: CursorParams = Depends(cursor_params),
) -> ApplicationTrackerResponse:
    """
    صفحه‌بندی مبتنی بر نشانگر (Cursor Pagination): جدیدترین تغییر وضعیت اول
    (updated_at DESC) — از همان ایندکس مرکب (candidate_id, updated_at, id)
    روی applications استفاده می‌کند که برای این کوئری هم فیلتر candidate_id
    و هم ترتیب صفحه‌بندی را پوشش می‌دهد.
    """
    candidate = await get_or_create_candidate_profile(db, current_user)
    await db.commit()

    query = (
        select(Application.id, Application.job_id, Job.title, Application.current_status, Application.updated_at)
        .join(Job, Job.id == Application.job_id)
        .where(Application.candidate_id == candidate.id)
    )

    cursor_page = await paginate_by_cursor(
        db,
        query,
        sort_column=Application.updated_at,
        id_column=Application.id,
        params=page,
        descending=True,
    )

    items = [
        ApplicationTrackerItem(
            application_id=row.id,
            job_id=row.job_id,
            job_title=row.title,
            current_status=row.current_status,
            updated_at=row.updated_at,
        )
        for row in cursor_page.items
    ]

    return ApplicationTrackerResponse(
        items=items,
        next_cursor=cursor_page.next_cursor,
        previous_cursor=cursor_page.previous_cursor,
        has_next=cursor_page.has_next,
        has_previous=cursor_page.has_previous,
    )


@router.get(
    "/me/offers",
    response_model=OfferInboxResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="صندوق ورودی پیشنهادهای شغلی فعال (درخواست‌هایی با وضعیت Offer)",
    dependencies=[Depends(require_roles("Candidate"))],
)
async def list_my_offers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: CursorParams = Depends(cursor_params),
) -> OfferInboxResponse:
    """
    صفحه‌بندی مبتنی بر نشانگر (Cursor Pagination) — همان الگوی سایر لیست‌ها
    (updated_at DESC)؛ فیلتر current_status از ایندکس ix_applications_current_status
    و فیلتر candidate_id + ترتیب از ایندکس مرکب (candidate_id, updated_at, id) استفاده می‌کند.
    """
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
    )

    cursor_page = await paginate_by_cursor(
        db,
        query,
        sort_column=Application.updated_at,
        id_column=Application.id,
        params=page,
        descending=True,
    )

    items = [
        OfferInboxItem(
            application_id=row.id,
            job_id=row.job_id,
            job_title=row.title,
            company_name=row.name,
            updated_at=row.updated_at,
        )
        for row in cursor_page.items
    ]

    return OfferInboxResponse(
        items=items,
        next_cursor=cursor_page.next_cursor,
        previous_cursor=cursor_page.previous_cursor,
        has_next=cursor_page.has_next,
        has_previous=cursor_page.has_previous,
    )


@router.put(
    "/me/applications/{application_id}/respond",
    response_model=OfferResponseResult,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="پاسخ کارجو به یک پیشنهاد شغلی فعال (قبول یا رد)",
    dependencies=[Depends(require_roles("Candidate"))],
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


@router.get(
    "/search/",
    response_model=CandidateSearchResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Search"],
    summary="جستجوی ترکیبی متنی رزومه‌ها + فیلترهای ساختاریافته (فقط HR/Admin)",
    dependencies=[Depends(require_roles(*CANDIDATE_SEARCH_ROLES))],
)
async def search_candidates(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(
        default=None,
        max_length=500,
        description="عبارت جستجوی تمام‌متن درون رزومه‌ها؛ از عملگرهای منطقی AND/OR پشتیبانی می‌کند "
        "(مثلاً 'Python AND Django' یا 'React OR Vue'). Case-Insensitive است.",
    ),
    skills: Optional[list[str]] = Query(
        default=None,
        description="لیست مهارت‌های اجباری — کارجو باید در رزومه‌اش (طبق تحلیل موتور مهارت) همه‌ی "
        "این مهارت‌ها را داشته باشد. Case-Insensitive.",
    ),
    min_experience_years: Optional[float] = Query(
        default=None,
        ge=0,
        description="حداقل سال‌های سابقه‌ی کاری خالص (خروجی موتور مهارت).",
    ),
    min_ai_score: Optional[int] = Query(
        default=None,
        ge=0,
        le=100,
        description="حداقل نمره‌ی هوش مصنوعی (score_ai) در میان درخواست‌های این کارجو؛ فقط بین ۰ تا ۱۰۰ معتبر است.",
    ),
    page: CursorParams = Depends(cursor_params),
) -> CandidateSearchResponse:
    """
    موتور جستجوی ترکیبی: تمام فیلترهای ارسالی (q، skills، min_experience_years،
    min_ai_score) با هم AND می‌شوند و فقط کارجویانی برگردانده می‌شوند که
    هم‌زمان در همه‌ی شروط ارسالی صدق کنند (تقاطع نتایج، طبق معیار پذیرش تسک).
    هر پارامتر کاملاً اختیاری است؛ بدون هیچ فیلتری، تمام کارجویان صفحه‌بندی‌شده
    برمی‌گردند.

    اعتبارسنجی پارامترها (مثلاً min_ai_score بیرون از بازه‌ی ۰ تا ۱۰۰) از طریق
    محدودیت‌های Query (ge/le) توسط خودِ FastAPI/Pydantic انجام می‌شود و در
    صورت نامعتبر بودن، به‌صورت خودکار خطای ۴۲۲ Unprocessable Entity برمی‌گرداند
    (طبق معیار پذیرش تسک) — نیازی به بررسی دستی در بدنه‌ی تابع نیست.

    جستجوی متنی (q) روی ستون resumes.raw_text و با ایندکس GIN از پیش‌ساخته‌شده
    (بنگرید مایگریشن 852de21930b5) با to_tsvector('simple', ...) انجام می‌شود؛
    پیکربندی 'simple' عمداً انتخاب شده چون Stemming/Stopword زبان‌محور اعمال
    نمی‌کند (رزومه‌ها فارسی/انگلیسی/مخلوط‌اند) و Case-Insensitive بودن نتایج
    (طبق معیار پذیرش تسک) را تضمین می‌کند. عملگرهای AND/OR داخل q توسط
    app/core/search_query.py پارس و به عبارت tsquery معتبر تبدیل می‌شوند.

    فیلترهای ساختاریافته (skills، min_experience_years، min_ai_score) هرکدام
    به‌صورت یک زیرکوئری EXISTS پیاده شده‌اند تا کارجویی که چند رزومه/درخواست
    دارد، به‌ازای هر شرط، دیده شدن حداقل یک رزومه/درخواست منطبق کافی باشد؛
    خودِ ستون‌های نمایشی best_ai_score/best_experience_years هم با زیرکوئری
    MAX همبسته محاسبه می‌شوند تا HR بهترین سیگنال موجود را ببیند، نه فقط
    True/False تطابق.

    ⚠️ تصمیم مهندسی مستند: جدول candidates ستون زمانی (created_at) ندارد، پس
    برخلاف بقیه‌ی مسیرهای صفحه‌بندی‌شده‌ی پروژه که بر اساس created_at/updated_at
    مرتب می‌شوند، اینجا صفحه‌بندی مبتنی بر نشانگر روی خودِ Candidate.id (که
    primary key و ذاتاً ایندکس‌شده است) انجام می‌شود — ترتیب نمایش معنای
    زمانی ندارد ولی پایدار و بدون گم/تکرارشدن رکورد است.
    """
    tsquery_expr = build_resume_search_tsquery(q)

    best_ai_score_subquery = (
        select(func.max(Application.score_ai))
        .where(Application.candidate_id == Candidate.id)
        .correlate(Candidate)
        .scalar_subquery()
    )
    best_experience_subquery = (
        select(func.max(cast(Resume.skill_analysis["total_experience_years"].astext, Float)))
        .where(Resume.candidate_id == Candidate.id)
        .correlate(Candidate)
        .scalar_subquery()
    )

    query = (
        select(
            Candidate.id,
            Candidate.first_name,
            Candidate.last_name,
            Candidate.phone,
            Candidate.location,
            Candidate.skills,
            User.email,
            best_ai_score_subquery.label("best_ai_score"),
            best_experience_subquery.label("best_experience_years"),
        )
        .join(User, User.id == Candidate.user_id)
    )

    # --- فیلتر ۱: جستجوی تمام‌متن (raw_text) با پشتیبانی از AND/OR ---
    # عبارت to_tsvector از app/core/search_query.py می‌آید (نه اینجا Inline
    # نوشته شده) چون باید دقیقاً با عبارت ایندکس GIN مربوطه یکی باشد — هم
    # برای استفاده‌ی پستگرس از ایندکس، هم به‌خاطر رفع باگ توکنایزیشن کلمات
    # ترکیبی مثل "Node.js"/"C++" (توضیح کامل در همان تابع).
    if tsquery_expr is not None:
        query = query.where(
            select(Resume.id)
            .where(Resume.candidate_id == Candidate.id)
            .where(resume_fts_tsvector_expression(Resume.raw_text).op("@@")(func.to_tsquery("simple", tsquery_expr)))
            .exists()
        )

    # --- فیلتر ۲: حداقل سال‌های سابقه‌ی کاری (از تحلیل موتور مهارت) ---
    if min_experience_years is not None:
        query = query.where(
            select(Resume.id)
            .where(Resume.candidate_id == Candidate.id)
            .where(cast(Resume.skill_analysis["total_experience_years"].astext, Float) >= min_experience_years)
            .exists()
        )

    # --- فیلتر ۳: حداقل نمره‌ی هوش مصنوعی در میان درخواست‌های کارجو ---
    if min_ai_score is not None:
        query = query.where(
            select(Application.id)
            .where(Application.candidate_id == Candidate.id, Application.score_ai >= min_ai_score)
            .exists()
        )

    # --- فیلتر ۴: لیست مهارت‌های اجباری (باید همه‌شان تطبیق داده شوند، Case-Insensitive) ---
    if skills:
        for skill_name in skills:
            skill_name = skill_name.strip()
            if not skill_name:
                continue
            query = query.where(
                select(Resume.id)
                .where(Resume.candidate_id == Candidate.id)
                .where(
                    text(
                        "EXISTS (SELECT 1 FROM jsonb_array_elements_text("
                        "coalesce(resumes.skill_analysis -> 'skills', '[]'::jsonb)) AS _skill_elem "
                        "WHERE lower(_skill_elem) = lower(:skill_value))"
                    ).bindparams(skill_value=skill_name)
                )
                .exists()
            )

    cursor_page = await paginate_by_cursor(
        db,
        query,
        sort_column=Candidate.id,
        id_column=Candidate.id,
        params=page,
        descending=False,
    )

    items = [
        CandidateSearchItem(
            id=row.id,
            email=row.email,
            first_name=row.first_name,
            last_name=row.last_name,
            phone=row.phone,
            location=row.location,
            skills=row.skills or [],
            best_ai_score=row.best_ai_score,
            best_experience_years=row.best_experience_years,
        )
        for row in cursor_page.items
    ]

    return CandidateSearchResponse(
        items=items,
        next_cursor=cursor_page.next_cursor,
        previous_cursor=cursor_page.previous_cursor,
        has_next=cursor_page.has_next,
        has_previous=cursor_page.has_previous,
    )
