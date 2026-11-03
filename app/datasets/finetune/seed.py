"""
تولید داده‌ی کاملاً ساختگی برای آزمودن خط لوله‌ی دیتاست روی دیتابیس لوکال/تست — فقط محیط توسعه:

    python -m app.datasets.finetune.seed --pairs 11000

روی ENVIRONMENT=production اجرا نمی‌شود. هر رزومه‌ی ساختگی عمداً نام، ایمیل، تلفن (قالب‌های مختلف و ارقام فارسی)،
نشانی پروفایل، کد ملی، کد پستی و تاریخ تولد ساختگی دارد تا ناشناس‌ساز واقعاً آزموده شود؛ درصد کمی از رکوردها
عمداً «کثیف»اند (بدون رضایت، mojibake، کوتاه/بلند، تکراری، سابقه‌ی نامعقول، تحلیل ناموفق، بدون نمره، نویسه‌ی
خراب) تا هر قانون پاک‌سازی هم روی داده‌ی بزرگ دیده شود.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.agents.schema import UnifiedAnalysis
from app.core.config import settings
from app.core.security import hash_password
from app.core.tenancy import system_scope
from app.datasets.finetune import seed_data as data
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Company, Interview, Job, Resume, User

DEFAULT_PAIRS = 11_000
DEFAULT_TENANTS = 8
BATCH_SIZE = 400
DIRTY_WEIGHTS = (
    ("clean", 0.905),
    ("broken_chars", 0.02),
    ("mojibake_repairable", 0.01),
    ("mojibake", 0.01),
    ("no_consent", 0.02),
    ("duplicate", 0.01),
    ("short", 0.005),
    ("long", 0.004),
    ("experience_outlier", 0.004),
    ("failed_analysis", 0.004),
    ("no_score", 0.004),
    ("second_application", 0.004),
)
STATUSES = ("Draft", "Applied", "Screening", "Technical Interview", "HR Interview", "Offer", "Hired", "Rejected")


class ProductionRefusedError(RuntimeError):
    pass


def ensure_not_production(environment: str | None = None) -> None:
    if (environment or settings.ENVIRONMENT).strip().lower() in ("production", "prod"):
        raise ProductionRefusedError("seeder داده‌ی ساختگی روی Production اجرا نمی‌شود (ENVIRONMENT=production).")


@dataclass
class Person:
    first: str
    last: str
    email: str
    phone: str
    city: str
    handle: str


def _person(rng: random.Random, index: int) -> Person:
    persian = rng.random() < 0.7
    first = rng.choice(data.FIRST_NAMES_FA if persian else data.FIRST_NAMES_EN)
    last = rng.choice(data.LAST_NAMES_FA if persian else data.LAST_NAMES_EN)
    handle = f"{rng.choice(data.FIRST_NAMES_EN).lower()}{rng.choice(data.LAST_NAMES_EN).lower()}{index}"
    digits = f"9{rng.randint(10, 39)}{rng.randint(1000000, 9999999)}"
    return Person(first, last, f"{handle}@example.com", "0" + digits, rng.choice(data.CITIES), handle)


def _phone_variant(rng: random.Random, phone: str) -> str:
    body = phone[1:]
    variants = (
        f"0{body[:3]} {body[3:6]} {body[6:]}",
        f"+98 {body[:3]} {body[3:6]} {body[6:]}",
        phone,
        phone.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
        f"0098-{body}",
    )
    return rng.choice(variants)


def _identity_lines(rng: random.Random, person: Person) -> list[str]:
    lines = [f"{person.first} {person.last}", f"ایمیل: {person.email} | تلفن: {_phone_variant(rng, person.phone)}"]
    if rng.random() < 0.5:
        lines.append(f"LinkedIn: linkedin.com/in/{person.handle} | Telegram: @{person.handle}")
    if rng.random() < 0.4:
        lines.append(f"تاریخ تولد: 13{rng.randint(60, 79)}/{rng.randint(1, 12):02d}/{rng.randint(1, 29):02d}")
    if rng.random() < 0.3:
        lines.append(f"کد ملی: {rng.randint(10**9, 10**10 - 1)}")
    if rng.random() < 0.3:
        lines.append(f"کد پستی: {rng.randint(10000, 99999)}-{rng.randint(10000, 99999)}")
    if rng.random() < 0.2:
        lines.append(f"تلفن ثابت: 021-{rng.randint(20000000, 89999999)}")
    lines.append(f"محل سکونت: {person.city}")
    return lines


def _positions(rng: random.Random, years: int) -> list[tuple[str, str, int, int]]:
    end = 2025
    positions = []
    for _ in range(rng.randint(1, 4)):
        length = max(1, years // 3 + rng.randint(0, 2))
        positions.append((rng.choice(data.TITLES), rng.choice(data.COMPANIES), end - length, end))
        end -= length
    return positions


def _resume_text(rng: random.Random, person: Person, skills: list[str], positions: list) -> str:
    lines = _identity_lines(rng, person)
    lines += ["", "خلاصه", " ".join(rng.sample(data.SUMMARIES, 2)), "", "سوابق کاری"]
    for title, company, start, end in positions:
        lines.append(f"{title} — {company} ({start}-{end})")
        lines += [f"- {item}" for item in rng.sample(data.ACHIEVEMENTS, rng.randint(2, 4))]
    lines += [
        "",
        "مهارت‌ها",
        "، ".join(skills),
        "",
        "تحصیلات",
        f"{rng.choice(data.EDUCATIONS)} — دانشگاه ساختگی شماره‌ی {rng.randint(1, 60)}",
    ]
    return "\n".join(lines)


def _entries(positions: list) -> list[dict]:
    return [
        {
            "index": index,
            "company": company,
            "job_title": title,
            "duration": f"{start}-{end}",
            "start_year": start,
            "end_year": end,
            "start_year_gregorian": start,
            "end_year_gregorian": end,
            "is_valid": True,
        }
        for index, (title, company, start, end) in enumerate(positions)
    ]


def _skill_items(skills: list[str]) -> list[dict]:
    item = {"category": "general", "evidence_count": 1, "inferred": False, "confidence": 0.9}
    return [{"name": skill, "core": skill, **item} for skill in skills]


def _soft_items(rng: random.Random) -> list[dict]:
    return [
        {"key": key, "label_fa": label, "score": round(rng.uniform(0.3, 1.0), 2), "evidence": ["ساختگی"]}
        for key, label in rng.sample(data.SOFT_SKILLS, rng.randint(1, 4))
    ]


def _analysis(rng: random.Random, skills: list[str], job_skills: tuple, positions: list, kind: str) -> dict:
    matched = [skill for skill in job_skills if skill in skills]
    years = float(sum(end - start for _, _, start, end in positions))
    if kind == "experience_outlier":
        years = float(rng.randint(55, 80))
    raw_score = 15 + 60 * len(matched) / max(1, len(job_skills)) + 2 * min(years, 10) + rng.gauss(0, 6)
    flags = [
        dict(zip(("code", "severity", "message"), item), source="experience")
        for item in rng.sample(data.FLAG_TEMPLATES, rng.randint(0, 2))
    ]
    timing = {"start_ms": 0.0, "end_ms": 10.0, "duration_ms": 10.0}
    analysis = {
        "status": "failed" if kind == "failed_analysis" else "completed",
        "skills": {"status": "completed", "items": _skill_items(skills)},
        "experience": {"status": "completed", "total_experience_years": years, "entries": _entries(positions)},
        "soft_skills": {"status": "completed", "confidence": 0.7, "items": _soft_items(rng)},
        "flags": flags,
        "matching": {"score": round(max(0.0, min(100.0, raw_score)), 2), "matched_required_skills": matched},
        "timings_ms": {"skill": timing, "experience": timing, "soft_skills": timing},
    }
    return UnifiedAnalysis.model_validate(analysis).model_dump(mode="json")


def _corrupt(rng: random.Random, text: str, kind: str) -> str:
    if kind == "broken_chars":
        return text.replace("\n", "\u200b\n", 2).replace(" ", "\ufffd ", 1) + "\x07"
    if kind == "mojibake_repairable":
        return text.encode("utf-8").decode("latin-1")
    if kind == "mojibake":
        return text.encode("utf-8").decode("cp1252", errors="ignore")
    if kind == "short":
        return text[:80]
    if kind == "long":
        return text + "\n" + "\n".join(rng.choice(data.ACHIEVEMENTS) + f" (پروژه‌ی {i})" for i in range(700))
    return text


@dataclass
class SeedState:
    rng: random.Random
    password_hash: str
    tenants: list = field(default_factory=list)  # (company, hr_user, jobs)
    # (سازمان، آگهی، متن) آخرین جفت — رکورد «duplicate» همان رزومه را با حساب دیگری برای همان آگهی می‌فرستد
    last_pair: tuple | None = None
    pairs: int = 0


async def _create_tenants(db, state: SeedState, count: int) -> None:
    rng = state.rng
    for index in range(count):
        owner = User(
            email=f"seed-hr-{uuid.uuid4().hex[:10]}@example.com", password_hash=state.password_hash, role="Admin"
        )
        db.add(owner)
        await db.flush()
        company = Company(name=f"سازمان ساختگی {index + 1}", owner_id=owner.id)
        db.add(company)
        await db.flush()
        owner.tenant_id = company.id
        jobs = []
        for title, department, skills in data.JOBS:
            job = Job(
                title=title,
                department=department,
                description=f"{title} برای تیم {department}. " + " ".join(rng.sample(data.SUMMARIES, 2)),
                skills_required=list(skills),
                required_seniority=rng.choice(data.SENIORITIES),
                required_education=rng.choice(data.EDUCATIONS),
                created_by=owner.id,
                tenant_id=company.id,
            )
            db.add(job)
            jobs.append(job)
        state.tenants.append((company, owner, jobs))
    await db.commit()


def _pick_kind(rng: random.Random) -> str:
    return rng.choices([kind for kind, _ in DIRTY_WEIGHTS], weights=[weight for _, weight in DIRTY_WEIGHTS])[0]


def _resume_for(state: SeedState, person: Person, job: Job, kind: str) -> tuple[str, dict]:
    rng = state.rng
    skills = rng.sample(list(job.skills_required), rng.randint(1, len(job.skills_required)))
    skills += rng.sample(data.EXTRA_SKILLS, rng.randint(1, 5))
    positions = _positions(rng, rng.randint(1, 15))
    text = _corrupt(rng, _resume_text(rng, person, skills, positions), kind)
    if kind == "duplicate" and state.last_pair is not None and state.last_pair[1] is job:
        text = state.last_pair[2]
    return text, _analysis(rng, skills, tuple(job.skills_required), positions, kind)


def _application_rows(state: SeedState, candidate: Candidate, person: Person, tenant, kind: str) -> list:
    rng = state.rng
    company, owner, jobs = tenant
    count = 2 if kind == "second_application" else 1
    rows = []
    duplicate = kind == "duplicate" and state.last_pair is not None
    for job in [state.last_pair[1]] if duplicate else rng.sample(jobs, count):
        text, analysis = _resume_for(state, person, job, kind)
        personal = {"name": f"{person.first} {person.last}", "email": person.email, "phone": person.phone}
        rows.append(
            Resume(
                candidate_id=candidate.id,
                tenant_id=company.id,
                file_url=f"seed/{uuid.uuid4().hex}.pdf",
                raw_text=text,
                parsed_data={"personal_info": personal},
                agent_analysis=analysis,
            )
        )
        score = None if kind == "no_score" else round(analysis["matching"]["score"])
        application = Application(
            job_id=job.id,
            candidate_id=candidate.id,
            tenant_id=company.id,
            current_status=rng.choice(STATUSES),
            score_ai=score,
        )
        rows.append(application)
        state.last_pair = (tenant, job, text)
        state.pairs += 1
    return rows


def _interview_for(state: SeedState, application: Application, owner: User) -> Interview | None:
    if application.current_status in ("Draft", "Applied", "Screening") or state.rng.random() < 0.3:
        return None
    score = round(state.rng.uniform(4, 10), 1)
    return Interview(
        application_id=application.id,
        interviewer_id=owner.id,
        tenant_id=application.tenant_id,
        status="Completed",
        evaluation_scores={"technical_skill": score},
        overall_score=score,
    )


async def _seed_candidate(db, state: SeedState, index: int) -> None:
    rng = state.rng
    person = _person(rng, index)
    kind = _pick_kind(rng)
    consent = None if kind == "no_consent" else datetime.now(timezone.utc)
    user = User(
        email=person.email,
        password_hash=state.password_hash,
        role="Candidate",
        data_consent_at=consent,
        data_consent_version="v1" if consent else None,
    )
    db.add(user)
    await db.flush()
    candidate = Candidate(
        user_id=user.id,
        first_name=person.first,
        last_name=person.last,
        phone=person.phone,
        location=person.city,
        skills=[],
    )
    db.add(candidate)
    await db.flush()
    tenant = state.last_pair[0] if kind == "duplicate" and state.last_pair else rng.choice(state.tenants)
    rows = _application_rows(state, candidate, person, tenant, kind)
    db.add_all(rows)
    await db.flush()
    interviews = [_interview_for(state, row, tenant[1]) for row in rows if isinstance(row, Application)]
    db.add_all([interview for interview in interviews if interview is not None])


async def seed(pairs: int = DEFAULT_PAIRS, tenants: int = DEFAULT_TENANTS, seed_value: int = 7, db=None) -> int:
    """خروجی: تعداد جفت «درخواست ↔ رزومه»ی ساخته‌شده. db برای تست؛ بدون آن یک Session تازه باز می‌شود."""
    ensure_not_production()
    state = SeedState(rng=random.Random(seed_value), password_hash=hash_password(uuid.uuid4().hex))
    if db is None:
        async with AsyncSessionLocal() as session:
            async with system_scope(session):
                return await _seed_into(session, state, pairs, tenants)
    return await _seed_into(db, state, pairs, tenants)


async def _seed_into(db, state: SeedState, pairs: int, tenants: int) -> int:
    await _create_tenants(db, state, tenants)
    index = 0
    while state.pairs < pairs:
        await _seed_candidate(db, state, index)
        index += 1
        if index % BATCH_SIZE == 0:
            await db.commit()
    await db.commit()
    return state.pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.datasets.finetune.seed", description="داده‌ی ساختگی (فقط توسعه)"
    )
    parser.add_argument("--pairs", type=int, default=DEFAULT_PAIRS)
    parser.add_argument("--tenants", type=int, default=DEFAULT_TENANTS)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        created = asyncio.run(seed(args.pairs, args.tenants, args.seed))
    except ProductionRefusedError as error:
        print(str(error), file=sys.stderr)
        return 3
    print(f"seeded_pairs={created}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
