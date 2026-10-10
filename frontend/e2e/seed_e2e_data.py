"""
داده‌ی آزمایشی تست‌های E2E — داخل کانتینر بک‌اند اجرا می‌شود (بنگرید e2e/global-setup.ts):

    docker compose exec -T backend_api python - seed <run_id>    < e2e/seed_e2e_data.py
    docker compose exec -T backend_api python - cleanup <run_id> < e2e/seed_e2e_data.py

همه‌ی رکوردها با یک run_id یکتا علامت‌گذاری می‌شوند تا cleanup دقیقاً و فقط همان‌ها را
پاک کند و چند اجرای هم‌زمان/پشت‌سرهم با هم تداخل نداشته باشند.
"""

import asyncio
import json
import sys

from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Job, StatusHistory, User

E2E_PASSWORD = "E2e!Passw0rd"

# (نام نمایشی کارت، وضعیت اولیه روی بورد، امتیاز هوش مصنوعی)
CANDIDATES = [
    ("Sara E2E", "Draft", 72),
    ("Reza E2E", "Screening", 88),
    ("Nima E2E", "Offer", 64),
]


def _email(role: str, run_id: str, index: int = 0) -> str:
    return f"e2e-{role}-{index}-{run_id}@example.com"


async def seed(run_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        hr_user = User(email=_email("hr", run_id), password_hash=hash_password(E2E_PASSWORD), role="HR_Manager")
        db.add(hr_user)
        await db.flush()

        job = Job(
            title=f"E2E Backend Developer {run_id}",
            department="Engineering",
            skills_required=["Python", "FastAPI"],
            status="Active",
            created_by=hr_user.id,
        )
        db.add(job)
        await db.flush()

        for index, (full_name, status, score) in enumerate(CANDIDATES, start=1):
            candidate_user = User(
                email=_email("candidate", run_id, index), password_hash=hash_password(E2E_PASSWORD), role="Candidate"
            )
            db.add(candidate_user)
            await db.flush()
            first_name, last_name = full_name.split(" ")
            candidate = Candidate(user_id=candidate_user.id, first_name=first_name, last_name=last_name)
            db.add(candidate)
            await db.flush()
            db.add(Application(job_id=job.id, candidate_id=candidate.id, current_status=status, score_ai=score))

        await db.commit()
        return {"hrEmail": hr_user.email, "password": E2E_PASSWORD, "jobTitle": job.title, "jobId": str(job.id)}


async def cleanup(run_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        user_ids = (
            (await db.execute(select(User.id).where(User.email.like(f"e2e-%-{run_id}@example.com")))).scalars().all()
        )
        candidate_ids = (await db.execute(select(Candidate.id).where(Candidate.user_id.in_(user_ids)))).scalars().all()
        application_ids = (
            (await db.execute(select(Application.id).where(Application.candidate_id.in_(candidate_ids))))
            .scalars()
            .all()
        )

        await db.execute(delete(StatusHistory).where(StatusHistory.application_id.in_(application_ids)))
        await db.execute(delete(Application).where(Application.id.in_(application_ids)))
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(delete(Job).where(Job.created_by.in_(user_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()
        return {"deletedUsers": len(user_ids), "deletedApplications": len(application_ids)}


if __name__ == "__main__":
    command, run_identifier = sys.argv[1], sys.argv[2]
    action = seed if command == "seed" else cleanup
    print(json.dumps(asyncio.run(action(run_identifier))))
