"""
میکروسرویس آپلود رزومه (Resume Upload Service):
- POST /api/v1/resumes/upload   دریافت فایل رزومه (PDF/DOCX) به همراه job_id،
  ذخیره‌ی فیزیکی فایل در فضای ذخیره‌سازی (دیسک محلی یا Object Storage واقعی —
  بنگرید app/core/storage.py)، و ثبت اولیه‌ی درخواست کارجو (Application) با
  وضعیت پیش‌فرض Draft.

- GET  /api/v1/resumes/{resume_id}   جزئیات رزومه برای HR/Admin همان سازمان.

فقط کاربرانی با نقش Candidate اجازه‌ی آپلود رزومه‌ی خودشان را دارند.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.candidate_utils import get_or_create_candidate_profile
from app.core.deps import get_current_user, require_roles
from app.core.queue import enqueue_task
from app.core.storage import get_storage_backend
from app.core.storage import resolve_local_media_path
from fastapi.responses import FileResponse
from app.core.tenancy import system_scope
from app.db.session import get_db
from app.models import Application, Job, Resume, User
from app.schemas.resumes import ResumeDetailResponse, ResumeUploadResponse
from app.tasks.resume_processing import process_resume_task
from app.tasks.resume_model import now, public_state

router = APIRouter()

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
}
_ALLOWED_EXTENSIONS = {".pdf", ".docx"}
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # ۱۰ مگابایت
RESUME_VIEWER_ROLES = ("Admin", "HR_Manager")


@router.post(
    "/upload",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Resumes"],
    summary="آپلود فایل رزومه و ثبت اولیه‌ی درخواست کارجو (وضعیت Draft)",
    dependencies=[Depends(require_roles("Candidate"))],
)
async def upload_resume(
    job_id: uuid.UUID = Form(..., description="شناسه‌ی آگهی شغلی که کارجو برایش درخواست می‌دهد"),
    file: UploadFile = File(..., description="فایل فیزیکی رزومه — فقط PDF یا DOCX"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ResumeUploadResponse:
    """
    ترتیب پردازش:
    ۱. اعتبارسنجی فرمت فایل (فقط PDF/DOCX، هم از روی پسوند هم Content-Type) و حجم آن.
    ۲. اطمینان از وجود آگهی شغلی معتبر با job_id ارسالی -> در غیر این صورت 404.
    ۳. یافتن (یا ساخت خودکار) پروفایل کارجوی کاربر لاگین‌شده.
    ۴. ذخیره‌ی فیزیکی فایل در فضای ذخیره‌سازی (دیسک محلی یا Object Storage واقعی).
    ۵. باز کردن یک تراکنش واحد دیتابیس: درج ردیف در جدول resumes (همراه file_url)
       و درج ردیف در جدول applications با وضعیت پیش‌فرض Draft؛ هر دو با هم Commit
       یا (در صورت بروز خطا) هر دو با هم Rollback می‌شوند.
    ۶. پاسخ 202 Accepted، چون پردازش هوش مصنوعی رزومه در پس‌زمینه شروع می‌شود و
       این اندپوینت منتظر اتمامش نمی‌ماند.
    ۷. بلافاصله پس از موفقیت، یک کار (Task) پردازش رزومه به صف Redis اضافه
       می‌شود (بنگرید app/core/queue.py و app/tasks/resume_processing.py) —
       این کار به‌صورت fire-and-forget انجام می‌شود تا کارکرد اصلی سرور
       معطل ارتباط با Redis نماند.
    """
    original_filename = file.filename or ""
    file_extension = f".{original_filename.rsplit('.', 1)[-1].lower()}" if "." in original_filename else ""

    if file.content_type not in _ALLOWED_CONTENT_TYPES or file_extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="فقط فایل‌های رزومه با فرمت PDF یا DOCX پذیرفته می‌شوند.",
        )

    file_bytes = await file.read()

    if len(file_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="فایل ارسالی خالی است.")

    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="حجم فایل رزومه نباید بیشتر از ۱۰ مگابایت باشد.",
        )

    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="آگهی شغلی موردنظر یافت نشد.")

    candidate = await get_or_create_candidate_profile(db, current_user)

    storage_backend = get_storage_backend()
    file_url = await storage_backend.save_file(
        candidate_id=candidate.id,
        filename=original_filename,
        content=file_bytes,
        content_type=file.content_type or "application/octet-stream",
    )

    try:
        # چندمستاجری: رزومه و درخواست متعلق به سازمانِ صاحب آگهی‌اند (کارجو خودش سازمانی ندارد)
        resume = Resume(
            candidate_id=candidate.id,
            file_url=file_url,
            tenant_id=job.tenant_id,
            processing_state={
                "status": "queued",
                "stage": "queued",
                "attempt": 0,
                "updated_at": now(),
                "expires_at": now() + 86400,
            },
        )
        db.add(resume)
        await db.flush()

        application = Application(
            resume_id=resume.id,
            job_id=job.id,
            candidate_id=candidate.id,
            tenant_id=job.tenant_id,
            current_status="Draft",
        )
        db.add(application)

        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ثبت درخواست در دیتابیس با خطا مواجه شد.",
        )

    await db.refresh(application)

    # enqueue در thread انجام می‌شود؛ دریافت شناسه مانع اعلام صف‌گیری کاذب است.
    queued = await enqueue_task(process_resume_task, str(application.id), file_url, description="resume_analysis")
    if not queued:
        failed_state = {
            "status": "failed",
            "stage": "queued",
            "attempt": 0,
            "updated_at": now(),
            "error_code": "queue_unavailable",
        }
        # کارجو حق UPDATE رزومه ندارد؛ فقط فرادادهٔ رکوردی که همین درخواست ساخته ثبت می‌شود.
        async with system_scope(db):
            await db.execute(
                update(Resume)
                .where(Resume.id == resume.id, Resume.candidate_id == candidate.id, Resume.tenant_id == job.tenant_id)
                .values(processing_state=failed_state)
            )
            await db.commit()
        raise HTTPException(status_code=503, detail="فایل ذخیره شد؛ صف تحلیل موقتاً در دسترس نیست.")

    return ResumeUploadResponse(
        application_id=application.id,
        status=application.current_status,
        message="رزومه با موفقیت آپلود شد و درخواست شما ثبت گردید.",
    )


@router.get(
    "/{resume_id}",
    response_model=ResumeDetailResponse,
    tags=["Resumes"],
    summary="جزئیات یک رزومه (فقط HR/Admin همان سازمان)",
    responses={404: {"description": "رزومه وجود ندارد یا متعلق به سازمان دیگری است"}},
    dependencies=[Depends(require_roles(*RESUME_VIEWER_ROLES))],
)
async def get_resume(resume_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ResumeDetailResponse:
    """
    کوئری هیچ شرط سازمانی ندارد و عمداً هم نباید داشته باشد: فیلتر خودکار TenantMixin و پالیسی RLS
    جدول resumes، رزومه‌ی سازمان دیگر را نامرئی می‌کنند. پاسخ برای «وجود ندارد» و «مال سازمان دیگری
    است» یکسان (404) است تا وجود رزومه افشا نشود.
    """
    resume = (await db.execute(select(Resume).where(Resume.id == resume_id))).scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="رزومه یافت نشد.")
    result = ResumeDetailResponse.model_validate(resume)
    result.processing_state = public_state(resume.processing_state)
    return result


@router.get("/{resume_id}/processing", summary="وضعیت تحلیل؛ صاحب رزومه یا HR همان سازمان")
async def resume_processing_status(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # RLS و فیلتر ORM دسترسی کارجو به رزومهٔ خودش و HR به سازمان خودش را اعمال می‌کنند.
    if user.role not in (*RESUME_VIEWER_ROLES, "Candidate"):
        raise HTTPException(status_code=403, detail="دسترسی مجاز نیست.")
    resume = (await db.execute(select(Resume).where(Resume.id == resume_id))).scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="رزومه یافت نشد.")
    return {"processing_state": public_state(resume.processing_state)}


@router.get("/{resume_id}/file", summary="دریافت خصوصی فایل؛ صاحب رزومه یا HR همان سازمان")
async def private_resume_file(
    resume_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    if user.role not in (*RESUME_VIEWER_ROLES, "Candidate"):
        raise HTTPException(403, "دسترسی مجاز نیست.")
    resume = (await db.execute(select(Resume).where(Resume.id == resume_id))).scalar_one_or_none()
    if resume is None or resume.file_url.startswith("deleted:"):
        raise HTTPException(404, "رزومه یافت نشد.")
    path = resolve_local_media_path(resume.file_url)
    if path is None:
        raise HTTPException(501, "private_storage_download_unavailable")
    if not path.is_file():
        raise HTTPException(404, "document_missing")
    media_type = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename="resume" + path.suffix.lower(),
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
