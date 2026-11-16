"""fixture ایزولهٔ ساختگی برای بررسی زنده؛ فقط ردیف‌ها و فایل اختصاصی خودش پاک می‌شوند."""

import asyncio
import json
import sys
import uuid
from pathlib import Path

import fitz
from sqlalchemy import select, delete
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.resume_parser import parse_resume_text
from app.core.text_extraction import extract_raw_text
from app.core.analysis_evidence import build_analysis
from app.db.session import worker_session_factory
from app.models import User, Candidate, Job, Resume, Application

JOURNAL = Path("/tmp/phase6-target.json")


async def run():
    assert make_url(settings.DATABASE_URL).database == "ats_preview", "local preview database required"
    async with worker_session_factory() as factory:
        async with factory() as db:
            if "--cleanup" in sys.argv:
                target = json.loads(JOURNAL.read_text())
                file = Path(target["file"]).resolve()
                assert file.parent == (Path(settings.MEDIA_ROOT) / "resumes").resolve()
                assert file.name.startswith("phase6-synthetic-")
                for model, key in [
                    (Application, "application"),
                    (Resume, "resume"),
                    (Job, "job"),
                    (Candidate, "candidate"),
                    (User, "user"),
                ]:
                    await db.execute(delete(model).where(model.id == uuid.UUID(target[key])))
                await db.commit()
                file.unlink(missing_ok=True)
                JOURNAL.unlink()
                print(json.dumps(dict(cleaned_synthetic_fixture=True)))
                return
            assert not JOURNAL.exists(), "synthetic fixture already exists"
            hr = (await db.execute(select(User).where(User.email == "hr@ats-preview.example.com"))).scalar_one()
            target = {k: str(uuid.uuid4()) for k in ["user", "candidate", "job", "resume", "application"]}
            file = Path(settings.MEDIA_ROOT) / "resumes" / ("phase6-synthetic-" + target["resume"] + ".pdf")
            file.parent.mkdir(parents=True, exist_ok=True)
            doc = fitz.open()
            page = doc.new_page()
            lines = [
                "MIRA HART",
                "Harbor City, Iran",
                "SUMMARY",
                "Python backend development.",
                "EXPERIENCE",
                "Software Engineer | Harbor Systems",
                "2024/01/01 - 2025/01/01",
                "Built Python services serving 10000 users.",
                "SKILLS",
                "Python 3.11; FastAPI; Postgres",
                "LANGUAGES",
                "Persian: Native | English: Upper-intermediate",
            ]
            for i, line in enumerate(lines):
                page.insert_text((40, 50 + i * 35), line, fontsize=12)
            page = doc.new_page()
            page.insert_text((40, 60), "Synthetic supporting page - no personal data", fontsize=12)
            content = doc.tobytes()
            doc.close()
            file.write_bytes(content)
            layout = extract_raw_text(content, "synthetic.pdf", with_layout=True)
            raw = layout.pop("raw_text")
            parsed = parse_resume_text(raw, layout=layout).model_dump()
            parsed["_extraction"] = layout
            parsed["_evidence_analysis"] = build_analysis(
                raw, parsed["structured"], {"skills_required": ["Python or Java", "Docker"]}, layout
            )
            db.add(
                User(
                    id=uuid.UUID(target["user"]),
                    email="phase6-" + target["user"] + "@example.invalid",
                    password_hash="disabled",
                    role="Candidate",
                )
            )
            await db.flush()
            db.add(
                Candidate(
                    id=uuid.UUID(target["candidate"]),
                    user_id=uuid.UUID(target["user"]),
                    first_name="Synthetic",
                    last_name="Fixture",
                )
            )
            db.add(
                Job(
                    id=uuid.UUID(target["job"]),
                    title="Synthetic phase 6",
                    tenant_id=hr.tenant_id,
                    created_by=hr.id,
                    skills_required=["Python"],
                )
            )
            await db.flush()
            db.add(
                Resume(
                    id=uuid.UUID(target["resume"]),
                    candidate_id=uuid.UUID(target["candidate"]),
                    tenant_id=hr.tenant_id,
                    file_url=settings.MEDIA_BASE_URL.rstrip("/") + "/resumes/" + file.name,
                    raw_text=raw,
                    parsed_data=parsed,
                    processing_state={"status": "succeeded", "stage": "complete", "attempt": 1},
                )
            )
            await db.flush()
            db.add(
                Application(
                    id=uuid.UUID(target["application"]),
                    candidate_id=uuid.UUID(target["candidate"]),
                    job_id=uuid.UUID(target["job"]),
                    resume_id=uuid.UUID(target["resume"]),
                    tenant_id=hr.tenant_id,
                    current_status="Draft",
                )
            )
            await db.commit()
            target["file"] = str(file)
            target["synthetic"] = True
            JOURNAL.write_text(json.dumps(target))
            print(json.dumps(dict(application_id=target["application"], synthetic=True)))


asyncio.run(run())
