#!/usr/bin/env bash
# =============================================================================
# راستی‌آزمایی اکوسیستم چندعاملی پردازش رزومه روی سرور Production — با یک سازمان و رزومه‌ی آزمایشی موقت که در
# پایان کامل پاک می‌شوند:
#
#   cd /opt/ats-smart && bash deploy/agents-check.sh            # + benchmark روی CPU خود سرور (یک دور)
#   SKIP_BENCHMARK=1 bash deploy/agents-check.sh               # فقط مسیر واقعی
#
#   ۰. LangGraph فقط در Worker بارگذاری می‌شود (API آن را import نمی‌کند)
#   ۱. یک رزومه‌ی خام (DOCX) از مسیر واقعی صف «resumes» به Worker داده می‌شود: عامل ناظر، سه عامل موازی،
#      جمع‌بندی ← زمان هر عامل و هم‌پوشانی‌شان، خلاصه‌ی JSON یکپارچه (بدون اطلاعات شخصی)، نمره، رمزشده بودن ستون
#   ۲. مقایسه‌ی زمان خط لوله‌ی خطی و چندعاملی روی همین سرور (۲۴ رزومه: اسکن‌شده/متنی/DOCX فارسی و انگلیسی)
# =============================================================================
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

RUN_ID="$(date +%Y%m%d%H%M%S)"
REPORT_DIR="${REPORT_DIR:-reports}"
REPORT="${REPORT_DIR}/agents-${RUN_ID}.log"
mkdir -p "${REPORT_DIR}"
PASSED=0
FAILED=0

section() { printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$*" | tee -a "$REPORT"; }
pass() { PASSED=$((PASSED + 1)); printf '  \033[32m✔ PASS\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
fail() { FAILED=$((FAILED + 1)); printf '  \033[31m✘ FAIL\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
info() { printf '          %s\n' "$*" | tee -a "$REPORT"; }
collect() {
    while IFS= read -r line; do
        case "$line" in
            "RESULT PASS "*) pass "${line#RESULT PASS }" ;;
            "RESULT FAIL "*) fail "${line#RESULT FAIL }" ;;
            "[BENCHMARK PASS]"*) pass "benchmark روی CPU همین سرور: نسبت زمان چندعاملی/خطی زیر سقف ۱٫۱۰" ;;
            "[BENCHMARK FAIL]"*) fail "benchmark روی CPU همین سرور: نسبت زمان بالای سقف ۱٫۱۰" ;;
            *) info "$line" ;;
        esac
    done
}

PROJECT="$(bash deploy/compose.sh config 2>/dev/null | sed -n 's/^name: //p' | head -n 1)"
PROJECT="${PROJECT:-ats-smart}"
container() {
    docker ps -q --filter "label=com.docker.compose.project=${PROJECT}" \
        --filter "label=com.docker.compose.service=$1" | head -n 1
}
API="$(container backend_api)"
WORKER="$(container worker)"
POSTGRES="$(container postgres_db)"
[[ -n "$API" && -n "$WORKER" && -n "$POSTGRES" ]] || { echo "API/Worker/PostgreSQL بالا نیستند" >&2; exit 2; }

printf '\033[1mATS Smart — راستی‌آزمایی اکوسیستم چندعاملی پردازش رزومه (سرور Production)\033[0m\n' | tee "$REPORT"
printf 'host: %s · %s · CPU: %s · نسخه: %s\n' "$(hostname)" "$(date '+%Y-%m-%d %H:%M:%S')" "$(nproc)" \
    "$(docker inspect --format '{{.Config.Image}}' "$WORKER")" | tee -a "$REPORT"

# =============================================================================
section "۰. وابستگی‌ها و تنظیمات"
# =============================================================================
pipeline="$(docker exec "$WORKER" python -c 'from app.core.config import settings; print(settings.RESUME_PIPELINE)' 2>/dev/null)"
[[ "$pipeline" == "multi_agent" ]] && pass "Worker با RESUME_PIPELINE=multi_agent اجرا می‌شود" || fail "RESUME_PIPELINE=${pipeline:-?}"
lg="$(docker exec "$WORKER" python -c 'import langgraph, importlib.metadata as m; print(m.version("langgraph"))' 2>/dev/null)"
[[ -n "$lg" ]] && pass "LangGraph ${lg} در ایمیج Worker نصب است" || fail "LangGraph در Worker نیست"
api_lg="$(docker exec "$API" python -c 'import sys, app.main; print("langgraph" in sys.modules)' 2>/dev/null)"
[[ "$api_lg" == "False" ]] && pass "API، LangGraph را بارگذاری نمی‌کند (رم API بدون تغییر)" || fail "API هم LangGraph را بارگذاری کرده است"

# =============================================================================
section "۱. رزومه‌ی خام ← صف «resumes» ← عامل ناظر ← سه عامل موازی ← JSON یکپارچه"
# =============================================================================
docker exec -i -e RUN_ID="$RUN_ID" "$API" python - <<'PY' 2>&1 | collect
import asyncio, io, os, time, uuid
from docx import Document
from sqlalchemy import select, text
from app.agents.schema import UnifiedAnalysis
from app.core.crypto import FERNET_PREFIX
from app.core.queue import enqueue_task
from app.core.security import hash_password
from app.core.storage import LocalStorageBackend
from app.core.tenant_provisioning import provision_tenant
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Job, Resume, User
from app.tasks.resume_processing import process_resume_task

RUN_ID = os.environ["RUN_ID"]
LINES = [
    "Agents Check", "Summary",
    "Backend developer with 15 years of experience. I led a small team and we collaborated with stakeholders "
    "to deliver on time.",
    "Skills", "Python (12 years), FastAPI, Docker, Kubernetes, PostgreSQL",
    "Experience", "Senior Backend Developer", "Acme", "2019 - 2023", "Backend Developer", "Beta", "2021 - 2024",
    "Education", "B.Sc Computer Engineering", "University of Tehran",
]


def result(ok, message):
    print(f"RESULT {'PASS' if ok else 'FAIL'} {message}")


async def main():
    document = Document()
    for line in LINES:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)

    async with AsyncSessionLocal() as db:
        hr = User(email=f"agents-hr-{RUN_ID}@example.com", password_hash=hash_password(uuid.uuid4().hex), role="HR_Manager")
        tenant = await provision_tenant(db, name=f"Agents Check {RUN_ID}", owner=hr)
        job = Job(title="Backend Developer", skills_required=["Python", "Docker"], required_seniority="senior",
                  location="Tehran", description="FastAPI microservices", created_by=hr.id, tenant_id=tenant.id)
        user = User(email=f"agents-cand-{RUN_ID}@example.com", password_hash=hash_password(uuid.uuid4().hex), role="Candidate")
        db.add_all([job, user])
        await db.flush()
        candidate = Candidate(user_id=user.id, first_name="Agents", last_name="Check", location="Tehran")
        db.add(candidate)
        await db.flush()
        file_url = await LocalStorageBackend().save_file(
            candidate_id=candidate.id, filename="agents-check.docx", content=buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        application = Application(job_id=job.id, candidate_id=candidate.id, tenant_id=tenant.id, current_status="Applied")
        resume = Resume(candidate_id=candidate.id, tenant_id=tenant.id, file_url=file_url)
        db.add_all([application, resume])
        await db.commit()
        application_id, resume_id = str(application.id), resume.id

    job_id = await enqueue_task(process_resume_task, application_id, file_url)
    result(bool(job_id), "کار process_resume_task فقط با شناسه‌ی درخواست و آدرس فایل در صف «resumes» قرار گرفت")

    analysis, deadline = None, time.monotonic() + 180
    while time.monotonic() < deadline:
        async with AsyncSessionLocal() as db:
            stored = await db.get(Resume, resume_id)
            if stored.agent_analysis:
                analysis = UnifiedAnalysis.model_validate(stored.agent_analysis)
                raw = (await db.execute(text("SELECT left(agent_analysis, 12) FROM resumes WHERE id = :id"), {"id": resume_id})).scalar_one()
                score = (await db.get(Application, uuid.UUID(application_id))).score_ai
                break
        await asyncio.sleep(2)
    if analysis is None:
        result(False, "Worker در ۱۸۰ ثانیه رزومه را پردازش نکرد (لاگ: ./deploy/compose.sh logs worker)")
        return

    result(analysis.schema_version == "agents-v1", f"خروجی یکپارچه با قرارداد {analysis.schema_version} معتبر است · وضعیت: {analysis.status}")
    timings = analysis.timings_ms
    agents = ("skill_extraction", "experience_validation", "culture_fit_soft_skills")
    for name in ("supervisor_dispatch", *agents, "supervisor_aggregate", "total"):
        t = timings[name]
        print(f"{name:<26} {t.start_ms:9.1f} → {t.end_ms:9.1f} ms  ({t.duration_ms:.1f} ms)")
    windows = [timings[name] for name in agents]
    parallel = (
        all(w.start_ms >= timings["supervisor_dispatch"].end_ms for w in windows)
        and all(w.end_ms <= timings["supervisor_aggregate"].start_ms for w in windows)
        and max(w.start_ms for w in windows) < min(w.end_ms for w in windows)
    )
    result(parallel, "عامل ناظر سه عامل را بعد از توزیع، هم‌زمان اجرا کرد (پنجره‌های زمانی هم‌پوشانی دارند) و بعد از هر سه جمع‌بندی کرد")
    print(f"مهارت‌ها: {len(analysis.skills.items)} · سابقه‌ی تأییدشده: {analysis.experience.total_experience_years:g} سال · تداخل: {len(analysis.experience.overlaps)}")
    print(f"هشدارها: {', '.join(sorted({f.code for f in analysis.flags})) or '-'}")
    print(f"تعارض‌های حل‌شده: {', '.join(c.code for c in analysis.conflicts_resolved) or '-'}")
    print(f"مهارت‌های نرم: {', '.join(s.key for s in analysis.soft_skills.items) or '-'} · لحن غالب: {analysis.soft_skills.tone.dominant if analysis.soft_skills.tone else '-'}")
    m = analysis.matching
    print(f"نمره: پایه {m.base_score} + مهارت نرم {m.soft_skill_bonus} − اعتبارسنجی {m.validation_penalty} = {m.score} (score_ai={score})")
    result({"skill_years_capped", "claimed_total_overridden"} <= {c.code for c in analysis.conflicts_resolved},
           "تعارض‌ها حل و ثبت شدند: «۱۲ سال Python» و «۱۵ سال سابقه» به سابقه‌ی تأییدشده محدود شد")
    result(score == round(m.score), "applications.score_ai همان نمره‌ی عامل ناظر است")
    result(raw.startswith(FERNET_PREFIX[:6]), f"resumes.agent_analysis در دیتابیس رمزشده است ({raw}…)")

asyncio.run(main())
PY

# =============================================================================
section "۲. زمان پردازش: خطی در برابر چندعاملی، روی CPU همین سرور"
# =============================================================================
if [[ -n "${SKIP_BENCHMARK:-}" ]]; then
    info "رد شد (SKIP_BENCHMARK)"
else
    info "۲۴ رزومه (۸ PDF اسکن‌شده با OCR، ۸ PDF متنی، ۴ DOCX انگلیسی، ۴ DOCX فارسی) — چند دقیقه طول می‌کشد"
    docker cp loadtest/agent_benchmark.py "$WORKER":/tmp/agent_benchmark.py >/dev/null
    docker exec -e PYTHONPATH=/app -e PYTHONIOENCODING=utf-8 "$WORKER" python /tmp/agent_benchmark.py --rounds 1 2>&1 | collect
    docker exec "$WORKER" rm -f /tmp/agent_benchmark.py
fi

# =============================================================================
section "پاک‌سازی سازمان، کاربران، رزومه و فایل آزمایشی"
# =============================================================================
docker exec -i -e RUN_ID="$RUN_ID" "$API" python - <<'PY' 2>&1 | collect
import asyncio, os
from sqlalchemy import delete, or_, select
from app.core.redis_client import close_redis_connection
from app.core.storage import LocalStorageBackend
from app.core.tenant_provisioning import delete_owned_tenants
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Company, Job, Resume, StatusHistory, User

RUN_ID = os.environ["RUN_ID"]


async def main():
    async with AsyncSessionLocal() as db:
        tenant_ids = (await db.execute(select(Company.id).where(Company.name == f"Agents Check {RUN_ID}"))).scalars().all()
        resumes = (await db.execute(select(Resume).where(Resume.tenant_id.in_(tenant_ids)))).scalars().all()
        for resume in resumes:
            await LocalStorageBackend().delete_file(resume.file_url)
        candidate_ids = [resume.candidate_id for resume in resumes]
        user_ids = (await db.execute(select(Candidate.user_id).where(Candidate.id.in_(candidate_ids)))).scalars().all()
        owner_ids = (await db.execute(select(Company.owner_id).where(Company.id.in_(tenant_ids)))).scalars().all()
        app_ids = (await db.execute(select(Application.id).where(Application.tenant_id.in_(tenant_ids)))).scalars().all()
        await db.execute(delete(StatusHistory).where(StatusHistory.application_id.in_(app_ids)))
        await db.execute(delete(Application).where(Application.id.in_(app_ids)))
        await db.execute(delete(Resume).where(Resume.tenant_id.in_(tenant_ids)))
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(delete(Job).where(Job.tenant_id.in_(tenant_ids)))
        await delete_owned_tenants(db, owner_ids)
        await db.execute(delete(User).where(or_(User.id.in_(user_ids), User.id.in_(owner_ids))))
        await db.commit()
        print(f"RESULT PASS سازمان آزمایشی، {len(resumes)} رزومه و فایلش و {len(user_ids) + len(owner_ids)} کاربر پاک شد")
    await close_redis_connection()

asyncio.run(main())
PY

printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED" | tee -a "$REPORT"
info "گزارش کامل: ${PROJECT_DIR}/${REPORT}"
if ((FAILED == 0)); then
    printf '\033[1;32m[AGENTS PASS] عامل ناظر سه عامل را موازی اجرا کرد، خروجی یکپارچه معتبر است و زمان پردازش افزایش معناداری ندارد\033[0m\n' | tee -a "$REPORT"
    exit 0
fi
printf '\033[1;31m[AGENTS FAIL]\033[0m\n' | tee -a "$REPORT"
exit 1
