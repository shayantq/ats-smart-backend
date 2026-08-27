"""
میکروسرویس آپلود رزومه (Resume Upload Service):
- POST /api/v1/resumes/upload   دریافت فایل رزومه (PDF/DOCX) به همراه job_id،
  ذخیره‌ی فیزیکی فایل در فضای ذخیره‌سازی (دیسک محلی یا Object Storage واقعی —
  بنگرید app/core/storage.py)، و ثبت اولیه‌ی درخواست کارجو (Application) با
  وضعیت پیش‌فرض Draft.

فقط کاربرانی با نقش Candidate اجازه‌ی آپلود رزومه‌ی خودشان را دارند.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.candidate_utils import get_or_create_candidate_profile
from app.core.deps import get_current_user, require_roles
from app.core.queue import enqueue_task
from app.core.storage import get_storage_backend
from app.db.session import get_db
from app.models import Application, Job, Resume, User
from app.schemas.resumes import ResumeUploadResponse
from app.tasks.resume_processing import process_resume_task

router = APIRouter()

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
}
_ALLOWED_EXTENSIONS = {".pdf", ".docx"}
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # ۱۰ مگابایت


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
        resume = Resume(candidate_id=candidate.id, file_url=file_url)
        db.add(resume)

        application = Application(
            job_id=job.id,
            candidate_id=candidate.id,
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

    # ارسال کار پردازش رزومه به صف Redis — عمداً با create_task (نه await مستقیم)
    # تا خودِ درخواست HTTP اصلی معطل ارتباط با Redis نماند و پاسخ 202 فوری برگردد.
    asyncio.create_task(enqueue_task(process_resume_task, str(application.id), file_url))

    return ResumeUploadResponse(
        application_id=application.id,
        status=application.current_status,
        message="رزومه با موفقیت آپلود شد و درخواست شما ثبت گردید.",
    )
