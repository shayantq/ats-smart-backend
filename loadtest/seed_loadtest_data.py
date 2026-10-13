"""
داده‌ی تست بار — داخل کانتینر بک‌اند اجرا می‌شود (بنگرید README بخش «تست بار»):

    docker compose exec -T backend_api python - seed 5000 < loadtest/seed_loadtest_data.py
    docker compose exec -T backend_api python - cleanup   < loadtest/seed_loadtest_data.py

seed:    یک کاربر HR + یک آگهی فعال + N کارجو با ایمیل loadtest-candidate-<i>@example.com
         (همه با یک هش Bcrypt مشترک — ساختن ۵۰۰۰ هش جدا ~۱۷ دقیقه CPU می‌گرفت).
cleanup: حذف همه‌ی کاربران/کارجویان/درخواست‌ها/رزومه‌های تست بار و فایل‌های آپلودشده‌شان.
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

from sqlalchemy import delete, insert, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Job, Resume, StatusHistory, User

EMAIL_PREFIX = "loadtest-"
PASSWORD = "LoadTest!2026"
JOB_TITLE = "Load Test — Backend Developer"


async def seed(candidate_count: int) -> dict:
    async with AsyncSessionLocal() as db:
        password_hash = hash_password(PASSWORD)

        hr_user = User(email=f"{EMAIL_PREFIX}hr@example.com", password_hash=password_hash, role="HR_Manager")
        db.add(hr_user)
        await db.flush()
        job = Job(title=JOB_TITLE, skills_required=["Python", "FastAPI"], status="Active", created_by=hr_user.id)
        db.add(job)
        await db.flush()

        # درج دسته‌ای (Bulk) — چند ثانیه به‌جای چند دقیقه برای ۵۰۰۰ ردیف
        users = (
            await db.execute(
                insert(User).returning(User.id),
                [
                    {
                        "email": f"{EMAIL_PREFIX}candidate-{i}@example.com",
                        "password_hash": password_hash,
                        "role": "Candidate",
                    }
                    for i in range(candidate_count)
                ],
            )
        ).scalars()
        await db.execute(
            insert(Candidate),
            [{"user_id": user_id, "first_name": "Load", "last_name": f"Tester {i}"} for i, user_id in enumerate(users)],
        )
        await db.commit()
        return {"candidates": candidate_count, "jobId": str(job.id), "password": PASSWORD}


async def cleanup() -> dict:
    async with AsyncSessionLocal() as db:
        user_ids = (await db.execute(select(User.id).where(User.email.like(f"{EMAIL_PREFIX}%")))).scalars().all()
        candidate_ids = (await db.execute(select(Candidate.id).where(Candidate.user_id.in_(user_ids)))).scalars().all()
        job_ids = (await db.execute(select(Job.id).where(Job.created_by.in_(user_ids)))).scalars().all()
        application_ids = (
            (
                await db.execute(
                    select(Application.id).where(
                        Application.candidate_id.in_(candidate_ids) | Application.job_id.in_(job_ids)
                    )
                )
            )
            .scalars()
            .all()
        )

        await db.execute(delete(StatusHistory).where(StatusHistory.application_id.in_(application_ids)))
        await db.execute(delete(Application).where(Application.id.in_(application_ids)))
        await db.execute(delete(Resume).where(Resume.candidate_id.in_(candidate_ids)))
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()

    # فایل‌های رزومه‌ی آپلودشده‌ی همین کارجویان (media/resumes/<candidate_id>/...)
    resumes_root = Path(settings.MEDIA_ROOT) / "resumes"
    removed_dirs = 0
    for candidate_id in candidate_ids:
        directory = resumes_root / str(candidate_id)
        if directory.exists():
            shutil.rmtree(directory)
            removed_dirs += 1

    return {"deletedUsers": len(user_ids), "deletedApplications": len(application_ids), "removedFileDirs": removed_dirs}


if __name__ == "__main__":
    command = sys.argv[1]
    result = asyncio.run(seed(int(sys.argv[2])) if command == "seed" else cleanup())
    print(json.dumps(result))
