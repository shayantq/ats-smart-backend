#!/usr/bin/env bash
# =============================================================================
# راستی‌آزمایی چندمستاجری (Multi-Tenancy) روی کلاستر زنده — از مسیر واقعی API داخل Pod بک‌اند
#
#   bash k8s/tenant-isolation-check.sh
#   KEEP_DATA=1 bash k8s/tenant-isolation-check.sh    داده‌های آزمایشی پس از اجرا پاک نشوند
#
#   ۰. وضعیت مایگریشن: tenant_id اجباری، RLS فعال، نقش ats_app، هیچ ردیف بی‌سازمان
#   ۱. دو سازمان واقعی (ثبت‌نام Admin) ← HR هر سازمان (POST /tenant/users) ← آگهی ← رزومه‌ی کارجو
#   ۲. معیار ۱: GET لیست کارجویان/آگهی‌ها/درخواست‌ها فقط داده‌ی سازمان خود HR — بدون شناسه‌ی سازمان در درخواست
#   ۳. معیار ۲: HR سازمان B با شناسه‌ی مستقیم رزومه/درخواست/آگهی سازمان A → 404
#   ۴. دفاع در عمق: کوئری خام SQL زیر نقش ats_app (بدون فیلتر ORM) فقط ردیف‌های همان سازمان را می‌بیند
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

if grep -qi microsoft /proc/version 2>/dev/null && command -v kubectl.exe >/dev/null 2>&1; then
    kubectl() { kubectl.exe "$@"; }
fi
command -v kubectl >/dev/null 2>&1 || { echo "kubectl پیدا نشد" >&2; exit 2; }

cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-ats-smart}"
RUN_ID="$(date +%Y%m%d%H%M%S)"
REPORT_DIR="k8s/loadtest/reports"
REPORT="${REPORT_DIR}/tenant-isolation-${RUN_ID}.log"
mkdir -p "$REPORT_DIR"

printf '\033[1mATS Smart — راستی‌آزمایی ایزوله‌سازی چندمستاجری (RLS)\033[0m\n' | tee "$REPORT"
printf 'context: %s · %s\n' "$(kubectl config current-context)" "$(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$REPORT"

kubectl -n "$NAMESPACE" exec -i deploy/backend-api -c backend-api -- env \
    RUN_ID="$RUN_ID" KEEP_DATA="${KEEP_DATA:-0}" python - <<'PY' 2>&1 | tee -a "$REPORT"
import asyncio, io, os, uuid

import httpx
from docx import Document
from sqlalchemy import select, text

from app.core.security import create_access_token
from app.core.tenancy import SCOPE_TENANT, TenantContext, use_tenant_context
from app.db.session import AsyncSessionLocal
from app.models import Candidate, Resume, User

RUN = os.environ["RUN_ID"]
API = "http://127.0.0.1:8000/api/v1"
PASSWORD = f"Tenant!{RUN}"
failures = 0


def step(title: str) -> None:
    print(f"\n━━━ {title} ━━━", flush=True)


def check(condition: bool, message: str) -> None:
    global failures
    if condition:
        print(f"  ✔ PASS  {message}", flush=True)
    else:
        failures += 1
        print(f"  ✘ FAIL  {message}", flush=True)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def docx_resume(line: str) -> bytes:
    document = Document()
    document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def scalar(sql: str):
    async with AsyncSessionLocal() as session:
        return (await session.execute(text(sql))).scalar()


async def main() -> int:
    step("۰. وضعیت مایگریشن (d2f6b8a41c37) روی دیتابیس واقعی")
    revision = await scalar("SELECT version_num FROM alembic_version")
    check(revision == "d2f6b8a41c37", f"نسخه‌ی اسکیما: {revision}")
    tables = ("jobs", "applications", "resumes", "interviews", "status_history", "interview_question_sets", "interview_questions")
    not_null = await scalar(
        "SELECT count(*) FROM information_schema.columns WHERE column_name = 'tenant_id' AND is_nullable = 'NO' "
        f"AND table_name IN {tables}"
    )
    check(not_null == len(tables), f"ستون tenant_id اجباری روی {not_null} جدول عملیاتی")
    orphans = 0
    for table in tables:
        orphans += await scalar(f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL")
    check(orphans == 0, "هیچ ردیف بی‌سازمان (داده‌های پیشین به سازمان پیش‌فرض منتقل شدند)")
    rls = await scalar("SELECT string_agg(relname, ', ' ORDER BY relname) FROM pg_class WHERE relrowsecurity")
    check(bool(rls) and "resumes" in rls, f"RLS فعال: {rls}")
    policies = await scalar("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'")
    role = await scalar("SELECT rolname || ' (bypassrls=' || rolbypassrls || ')' FROM pg_roles WHERE rolname = 'ats_app'")
    check(policies >= 20 and role == "ats_app (bypassrls=false)", f"{policies} پالیسی RLS · نقش درخواست‌ها: {role}")

    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        step("۱. دو سازمان مستقل از مسیر واقعی API")
        orgs = {}
        for label in ("A", "B"):
            admin_email = f"tenant-{label.lower()}-admin-{RUN}@example.com"
            registered = await client.post(
                "/auth/register",
                json={"email": admin_email, "password": PASSWORD, "role": "Admin", "company_name": f"سازمان {label} ({RUN})"},
            )
            data = registered.json()["data"]
            admin_headers = bearer(create_access_token(data["user_id"], tenant_id=data["tenant_id"])[0])
            hr_email = f"tenant-{label.lower()}-hr-{RUN}@example.com"
            staff = await client.post(
                "/tenant/users", json={"email": hr_email, "password": PASSWORD, "role": "HR_Manager"}, headers=admin_headers
            )
            login = await client.post("/auth/login", json={"email": hr_email, "password": PASSWORD})
            hr_headers = bearer(login.json()["access_token"])
            job = await client.post(
                "/jobs/", json={"title": f"[Tenant {RUN}] Backend {label}", "skills_required": ["Python"]}, headers=hr_headers
            )
            orgs[label] = {"tenant_id": data["tenant_id"], "hr": hr_headers, "job_id": job.json()["job_id"]}
            check(
                registered.status_code == 201 and staff.status_code == 201 and login.status_code == 200 and job.status_code == 201,
                f"سازمان {label}: Admin ← HR (عضو همان سازمان) ← ورود (توکن با tid) ← آگهی — بدون ارسال شناسه‌ی سازمان",
            )

        async with AsyncSessionLocal() as session:
            for label in ("A", "B"):
                user = User(email=f"tenant-{label.lower()}-cand-{RUN}@example.com", password_hash="!", role="Candidate")
                session.add(user)
                await session.flush()
                session.add(Candidate(user_id=user.id, first_name=f"کارجوی {label}", last_name=RUN))
                orgs[label]["candidate_user"] = user.id
            await session.commit()
        for label in ("A", "B"):
            upload = await client.post(
                "/resumes/upload",
                data={"job_id": orgs[label]["job_id"]},
                files={"file": ("cv.docx", docx_resume(f"Python developer {label}"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                headers=bearer(create_access_token(str(orgs[label]["candidate_user"]))[0]),
            )
            orgs[label]["application_id"] = upload.json().get("application_id")
            async with AsyncSessionLocal() as session:
                candidate = (await session.execute(select(Candidate).where(Candidate.user_id == orgs[label]["candidate_user"]))).scalar_one()
                orgs[label]["candidate_id"] = str(candidate.id)
                resume = (await session.execute(select(Resume).where(Resume.candidate_id == candidate.id))).scalar_one()
                orgs[label]["resume_id"] = str(resume.id)
            check(
                upload.status_code == 202 and str(resume.tenant_id) == orgs[label]["tenant_id"],
                f"کارجوی {label} رزومه فرستاد ← رزومه و درخواست خودکار متعلق به سازمان {label} (سازمانِ صاحب آگهی)",
            )

        step("۲. معیار ۱ — هر GET فقط داده‌ی سازمان کاربر لاگین‌شده")
        for label, other in (("A", "B"), ("B", "A")):
            hr = orgs[label]["hr"]
            candidates = [item["candidate_id"] for item in (await client.get("/candidates/search/", headers=hr)).json()["items"]]
            check(
                orgs[label]["candidate_id"] in candidates and orgs[other]["candidate_id"] not in candidates,
                f"HR {label} ← GET /candidates/search/: {len(candidates)} کارجو، فقط متقاضیان سازمان {label}",
            )
            jobs = [item["job_id"] for item in (await client.get("/jobs/", params={"limit": 100}, headers=hr)).json()["items"]]
            check(
                orgs[label]["job_id"] in jobs and orgs[other]["job_id"] not in jobs,
                f"HR {label} ← GET /jobs/: {len(jobs)} آگهی، آگهی سازمان {other} دیده نمی‌شود",
            )

        step("۳. معیار ۲ — دسترسی مستقیم به شناسه‌ی رکورد سازمان دیگر ← 404")
        hr_b, a = orgs["B"]["hr"], orgs["A"]
        own = await client.get(f"/resumes/{a['resume_id']}", headers=a["hr"])
        foreign = await client.get(f"/resumes/{a['resume_id']}", headers=hr_b)
        missing = await client.get(f"/resumes/{uuid.uuid4()}", headers=hr_b)
        check(own.status_code == 200, f"HR A ← GET /resumes/{a['resume_id'][:8]}…: {own.status_code}")
        check(
            foreign.status_code == 404 and foreign.json() == missing.json(),
            f"HR B ← همان رزومه: {foreign.status_code} — پاسخ عیناً مثل رزومه‌ی ناموجود (وجودش افشا نمی‌شود)",
        )
        moved = await client.put(
            f"/applications/{a['application_id']}/status", json={"current_status": "Draft", "new_status": "Applied"}, headers=hr_b
        )
        closed = await client.delete(f"/jobs/{a['job_id']}", headers=hr_b)
        check(moved.status_code == 404 and closed.status_code == 404, f"HR B ← تغییر وضعیت درخواست A: {moved.status_code} · بستن آگهی A: {closed.status_code}")

    step("۴. دفاع در عمق — کوئری خام SQL بدون هیچ شرط سازمانی (شبیه‌سازی باگ بک‌اند)")
    context_b = TenantContext(SCOPE_TENANT, tenant_id=uuid.UUID(orgs["B"]["tenant_id"]), user_id=uuid.uuid4())
    with use_tenant_context(context_b):
        async with AsyncSessionLocal() as session:
            current_role = (await session.execute(text("SELECT current_user"))).scalar()
            leaked = (await session.execute(text(f"SELECT count(*) FROM resumes WHERE id = '{a['resume_id']}'"))).scalar()
            visible_tenants = (await session.execute(text("SELECT count(DISTINCT tenant_id) FROM resumes"))).scalar()
            hijack = (await session.execute(text(f"UPDATE jobs SET title = 'hacked' WHERE id = '{a['job_id']}' RETURNING id"))).all()
            await session.rollback()
    check(current_role == "ats_app", f"نقش دیتابیس درخواست‌ها: {current_role} (بدون BYPASSRLS)")
    check(leaked == 0 and visible_tenants == 1, "SELECT * FROM resumes در Context سازمان B: رزومه‌ی A نامرئی، فقط ۱ سازمان قابل مشاهده")
    check(hijack == [], "UPDATE آگهی سازمان A از Context سازمان B: صفر ردیف (PostgreSQL ردش کرد)")

    if os.environ.get("KEEP_DATA") != "1":
        async with AsyncSessionLocal() as session:
            users = f"(SELECT id FROM users WHERE email LIKE 'tenant-%-{RUN}@example.com')"
            tenants = f"(SELECT id FROM companies WHERE owner_id IN {users})"
            for statement in (
                f"DELETE FROM status_history WHERE tenant_id IN {tenants}",
                f"DELETE FROM applications WHERE tenant_id IN {tenants}",
                f"DELETE FROM resumes WHERE tenant_id IN {tenants}",
                f"DELETE FROM candidates WHERE user_id IN {users}",
                f"DELETE FROM jobs WHERE tenant_id IN {tenants}",
                f"DELETE FROM notifications WHERE user_id IN {users}",
                f"UPDATE users SET tenant_id = NULL WHERE id IN {users}",
                f"DELETE FROM companies WHERE owner_id IN {users}",
                f"DELETE FROM users WHERE email LIKE 'tenant-%-{RUN}@example.com'",
            ):
                await session.execute(text(statement))
            await session.commit()
        print("\n          داده‌های آزمایشی حذف شدند (KEEP_DATA=1 برای نگه‌داشتن)", flush=True)
    return 1 if failures else 0


code = asyncio.run(main())
print(f"EXIT_CODE {code}", flush=True)
PY
status=$?
if grep -q "^EXIT_CODE 0" "$REPORT" && ! grep -q "✘ FAIL" "$REPORT"; then
    printf '\n\033[1;32m[TENANT ISOLATION PASS] هر سازمان فقط داده‌ی خودش را می‌بیند — در لایه‌ی برنامه و دیتابیس\033[0m\n' | tee -a "$REPORT"
    exit 0
fi
printf '\n\033[1;31m[TENANT ISOLATION FAIL] جزئیات: %s\033[0m\n' "$REPORT" | tee -a "$REPORT"
exit 1
