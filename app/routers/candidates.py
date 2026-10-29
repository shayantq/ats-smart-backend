"""
میکروسرویس پورتال اختصاصی کارجو (Candidate Dashboard) + موتور جستجوی
پیشرفته‌ی کارجویان برای تیم منابع انسانی:
- GET/PUT /api/v1/candidates/me                          مشاهده/ویرایش پروفایل شخصی و تگ‌های مهارتی
- DELETE  /api/v1/candidates/me/                         حذف حساب (حق فراموش شدن — ناشناس‌سازی، app/core/privacy.py)
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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.candidate_utils import get_or_create_candidate_profile
from app.core.deps import get_current_user, require_roles
from app.core.pagination import CursorParams, cursor_params, paginate_by_cursor
from app.core.privacy import anonymize_candidate_account
from app.core.search_query import (
    resume_blind_index_condition,
    resume_experience_years_expression,
    resume_has_skill_condition,
)
from app.core.state_machine import ApplicationStatus, is_transition_allowed
from app.db.session import get_db
from app.models import Application, Candidate, Company, Job, Resume, StatusHistory, User
from app.schemas.candidate_search import CandidateSearchItem, CandidateSearchResponse
from app.schemas.candidates import (
    AccountDeletionResponse,
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


@router.delete(
    "/me/",
    response_model=AccountDeletionResponse,
    status_code=status.HTTP_200_OK,
    tags=["Candidate Portal"],
    summary="حذف حساب کارجو (حق فراموش شدن): ناشناس‌سازی هویت، حذف فایل رزومه، حفظ آمار استخدام",
    dependencies=[Depends(require_roles("Candidate"))],
)
async def delete_my_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccountDeletionResponse:
    """
    ردیف‌ها حذف نمی‌شوند (Hard Delete نیست): نام/تلفن/آدرس/ایمیل تصادفی یا NULL، فایل و متن رزومه پاک، حساب
    غیرفعال و همه‌ی نشست‌ها باطل می‌شوند؛ درخواست‌ها، وضعیت‌ها و نمره‌ها می‌مانند تا قیف استخدام و نرخ تبدیل
    سازمان‌ها تغییر نکند. درخواست دوم با همان توکن ← 401 (حساب دیگر وجود ندارد).
    """
    result = await anonymize_candidate_account(db, current_user)
    return AccountDeletionResponse(
        message="حساب شما حذف شد؛ اطلاعات هویتی و فایل رزومه‌تان پاک شد.",
        resumes_cleared=result.resumes_cleared,
        files_deleted=result.files_deleted,
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

    new_status = ApplicationStatus.ACCEPTED.value if payload.decision == "accept" else ApplicationStatus.REJECTED.value

    # بررسی دفاعی: طبق ماشین وضعیت، از Offer فقط Accepted/Rejected مجازند —
    # این شرط عملاً همیشه True است، ولی برای هم‌خوانی با گاردریل مرکزی نگه داشته شده.
    if not is_transition_allowed(application.current_status, new_status):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business Logic Violation")

    previous_status = application.current_status
    application.current_status = new_status
    db.add(application)

    history_entry = StatusHistory(
        application_id=application.id,
        # کارجو عضو سازمان نیست (Context بدون tenant)؛ سازمانِ تاریخچه همان سازمانِ درخواست است
        tenant_id=application.tenant_id,
        old_status=previous_status,
        new_status=new_status,
        changed_by=current_user.id,
    )
    db.add(history_entry)

    await db.commit()

    message = "پیشنهاد شغلی با موفقیت پذیرفته شد." if payload.decision == "accept" else "پیشنهاد شغلی رد شد."

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

    جستجوی متنی (q): متن رزومه (resumes.raw_text) در دیتابیس رمزشده است (حریم خصوصی)، پس جستجو روی
    ایندکس کور resumes.search_tokens (HMAC هر کلمه، ایندکس GIN) انجام می‌شود — تطبیق کلمه‌ی کامل و
    Case-Insensitive، بدون Stemming (رزومه‌ها فارسی/انگلیسی/مخلوط‌اند). عملگرهای AND/OR داخل q توسط
    app/core/search_query.py پارس می‌شوند.

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
    text_condition = resume_blind_index_condition(q, Resume.search_tokens)

    best_ai_score_subquery = (
        select(func.max(Application.score_ai))
        .where(Application.candidate_id == Candidate.id)
        .correlate(Candidate)
        .scalar_subquery()
    )
    best_experience_subquery = (
        select(func.max(resume_experience_years_expression(Resume.skill_analysis)))
        .where(Resume.candidate_id == Candidate.id)
        .correlate(Candidate)
        .scalar_subquery()
    )

    query = select(
        Candidate.id,
        Candidate.first_name,
        Candidate.last_name,
        Candidate.phone,
        Candidate.location,
        Candidate.skills,
        User.email,
        best_ai_score_subquery.label("best_ai_score"),
        best_experience_subquery.label("best_experience_years"),
    ).join(User, User.id == Candidate.user_id)

    # چندمستاجری: کارجو موجودیت سراسری است (می‌تواند به چند سازمان درخواست بدهد)؛ HR فقط کارجویانی را
    # می‌بیند که دست‌کم یک درخواست در سازمان خودش دارند. Application مدل TenantMixin است، پس این
    # زیرکوئری خودکار به سازمان جاری محدود می‌شود — پالیسی RLS جدول candidates هم همین را تضمین می‌کند.
    query = query.where(select(Application.id).where(Application.candidate_id == Candidate.id).exists())

    # --- فیلتر ۱: جستجوی متن رزومه (ایندکس کور) با پشتیبانی از AND/OR ---
    # نرمال‌سازی کلمات (شکستن «Node.js»/«C++» و ...) در app/core/search_query.py با همان تابعی انجام می‌شود
    # که ایندکس رزومه‌ها را ساخته است
    if text_condition is not None:
        query = query.where(select(Resume.id).where(Resume.candidate_id == Candidate.id).where(text_condition).exists())

    # --- فیلتر ۲: حداقل سال‌های سابقه‌ی کاری (از تحلیل موتور مهارت) ---
    if min_experience_years is not None:
        query = query.where(
            select(Resume.id)
            .where(Resume.candidate_id == Candidate.id)
            .where(resume_experience_years_expression(Resume.skill_analysis) >= min_experience_years)
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
            # ایندکس GIN مهارت‌ها (ix_resumes_skill_keys_gin) — بنگرید app/core/search_query.py
            query = query.where(
                select(Resume.id)
                .where(Resume.candidate_id == Candidate.id)
                .where(resume_has_skill_condition(Resume.skill_analysis, skill_name))
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
