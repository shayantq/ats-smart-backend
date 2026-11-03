"""
استخراج امن جفت‌های «رزومه ↔ آگهی» از دیتابیس.

- فقط‌خواندنی: Engine با postgresql_readonly ساخته می‌شود؛ هر تراکنش READ ONLY است و هیچ نوشتنی ممکن نیست.
- system_scope: خواندن بین‌سازمانی (همه‌ی tenant ها) با نقش ats_app و RLS، همان الگوی ابزارهای پلتفرم.
- جریانی (Streaming): نتیجه با Cursor سمت سرور و yield_per دسته‌دسته خوانده می‌شود؛ کل جدول در RAM نمی‌آید.
- رضایت: فقط کارجوهای فعالی که رضایت پردازش داده داده‌اند (data_consent_at) و حسابشان ناشناس نشده
  (anonymized_at).

پیوند درخواست به رزومه: ردیف Resume کلید خارجی به Application ندارد (هر دو در یک تراکنش آپلود ساخته می‌شوند و
فقط candidate_id/tenant_id مشترک دارند). اگر کارجو در آن سازمان یک رزومه‌ی پردازش‌شده دارد همان است؛ اگر چند تا،
رزومه‌ای انتخاب می‌شود که نمره‌ی تطابقش با score_ai همین درخواست برابر است (Worker همین را ذخیره کرده است)؛
اگر دقیقاً یکی جور نشد، جفت «مبهم» علامت می‌خورد و پاک‌سازی آن را کنار می‌گذارد.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.crypto import blind_index_token
from app.core.tenancy import system_scope
from app.datasets.finetune.anonymize import Identity
from app.datasets.finetune.records import JobInfo, PairSource
from app.models import Application, Candidate, Interview, Job, Resume, User

DEFAULT_BATCH_SIZE = 500
GROUP_PREFIX = "candidate:"


@asynccontextmanager
async def readonly_session(database_url: str | None = None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        database_url or settings.DATABASE_URL,
        poolclass=NullPool,
        execution_options={"postgresql_readonly": True},
        # لایه‌ی دوم: خود اتصال هم پیش‌فرض فقط‌خواندنی است (حتی اگر تراکنشی بدون گزینه‌ی بالا باز شود)
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    try:
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            async with system_scope(session):
                yield session
    finally:
        await engine.dispose()


def _eligible_filters():
    return (
        User.data_consent_at.is_not(None),
        User.anonymized_at.is_(None),
        User.is_active.is_(True),
    )


def _resume_join():
    return and_(
        Resume.candidate_id == Application.candidate_id,
        Resume.tenant_id == Application.tenant_id,
        Resume.agent_analysis.is_not(None),
    )


async def count_eligible_pairs(db: AsyncSession) -> int:
    query = (
        select(func.count(func.distinct(Application.id)))
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(User, User.id == Candidate.user_id)
        .join(Resume, _resume_join())
        .where(*_eligible_filters())
    )
    return int((await db.execute(query)).scalar_one())


def _pairs_query(batch_size: int):
    interview_score = (
        select(func.avg(Interview.overall_score))
        .where(Interview.application_id == Application.id, Interview.overall_score.is_not(None))
        .correlate(Application)
        .scalar_subquery()
    )
    return (
        select(
            Application.id.label("application_id"),
            Application.score_ai,
            Application.current_status,
            Application.candidate_id,
            interview_score.label("interview_score"),
            Job.title,
            Job.department,
            Job.description,
            Job.skills_required,
            Job.required_seniority,
            Job.required_education,
            Candidate.first_name,
            Candidate.last_name,
            Candidate.phone,
            Candidate.location,
            User.email,
            Resume.raw_text,
            Resume.parsed_data,
            Resume.agent_analysis,
        )
        .join(Job, Job.id == Application.job_id)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .join(User, User.id == Candidate.user_id)
        .join(Resume, _resume_join())
        .where(*_eligible_filters())
        .order_by(Application.id, Resume.id)
        .execution_options(yield_per=batch_size)
    )


def _identity(row) -> Identity:
    personal = ((row.parsed_data or {}).get("personal_info")) or {}
    names = [row.first_name, row.last_name, f"{row.first_name or ''} {row.last_name or ''}", personal.get("name")]
    return Identity(
        names=tuple(name for name in names if name and name.strip()),
        emails=tuple(email for email in (row.email, personal.get("email")) if email),
        phones=tuple(phone for phone in (row.phone, personal.get("phone")) if phone),
        locations=tuple(location for location in (row.location,) if location),
    )


def _analysis_score(analysis: dict | None) -> int | None:
    score = ((analysis or {}).get("matching") or {}).get("score")
    return round(score) if score is not None else None


def pick_resume(rows: list, score_ai: int | None):
    """رزومه‌ی متناظر یک درخواست بین چند رزومه‌ی همان کارجو در همان سازمان؛ None یعنی مبهم."""
    if len(rows) == 1:
        return rows[0]
    matches = [row for row in rows if score_ai is not None and _analysis_score(row.agent_analysis) == score_ai]
    return matches[0] if len(matches) == 1 else None


def _to_source(rows: list) -> PairSource:
    first = rows[0]
    chosen = pick_resume(rows, first.score_ai)
    job = JobInfo(
        title=first.title or "",
        department=first.department,
        description=first.description,
        skills_required=tuple(first.skills_required or ()),
        seniority=first.required_seniority,
        education=first.required_education,
    )
    return PairSource(
        candidate_key=blind_index_token(GROUP_PREFIX + str(first.candidate_id)),
        score_ai=first.score_ai,
        status=first.current_status,
        job=job,
        resume_text=chosen.raw_text if chosen is not None else None,
        analysis=chosen.agent_analysis if chosen is not None else None,
        identity=_identity(chosen if chosen is not None else first),
        interview_score=float(first.interview_score) if first.interview_score is not None else None,
        ambiguous_link=chosen is None,
    )


async def iter_pair_sources(db: AsyncSession, batch_size: int = DEFAULT_BATCH_SIZE) -> AsyncIterator[PairSource]:
    result = await db.stream(_pairs_query(batch_size))
    pending: list = []
    async for row in result:
        if pending and pending[0].application_id != row.application_id:
            yield _to_source(pending)
            pending = []
        pending.append(row)
    if pending:
        yield _to_source(pending)
