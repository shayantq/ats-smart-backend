#!/usr/bin/env bash
# =============================================================================
# راستی‌آزمایی حریم خصوصی (GDPR) روی سرور Production — فقط با یک سازمان و کارجوی آزمایشی موقت که در پایان
# کامل پاک می‌شوند (داده‌ی واقعی و آمار سازمان‌های واقعی دست نمی‌خورد):
#
#   cd /opt/ats-smart && bash deploy/privacy-check.sh
#
#   ۰. کلید: فقط در secrets/pii.env (۶۰۰)، نه در .env و نه در ایمیج؛ فقط کانتینرهای API و Worker آن را دارند
#   ۱. بازرسی مستقیم دیتابیس (psql داخل کانتینر پستگرس، مثل DBeaver): نام، تلفن، آدرس، متن و داده‌ی رزومه
#      رمزشده‌اند؛ همان رکورد از API (کارشناس HR مجاز) خوانا برمی‌گردد
#   ۲. حذف حساب کارجو (DELETE /api/v1/candidates/me/): ردیف‌ها می‌مانند، هویت پاک می‌شود و قیف استخدام
#      سازمان قبل و بعد دقیقاً یکی است
# =============================================================================
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

RUN_ID="$(date +%Y%m%d%H%M%S)"
REPORT_DIR="${REPORT_DIR:-reports}"
REPORT="${REPORT_DIR}/privacy-${RUN_ID}.log"
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
            "STATE "*) printf '%s\n' "${line#STATE }" > "$STATE" ;;
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
POSTGRES="$(container postgres_db)"
PUBLIC_BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env 2>/dev/null | cut -d= -f2-)"
[[ -n "$API" && -n "$POSTGRES" && -n "$PUBLIC_BASE_URL" ]] || { echo "API/PostgreSQL بالا نیستند یا PUBLIC_BASE_URL در .env نیست" >&2; exit 2; }

STATE="$(mktemp)"
trap 'rm -f "$STATE"' EXIT
psql_raw() {  # کوئری خام روی دیتابیس، مثل یک کلاینت دیتابیس (بدون برنامه و بدون کلید)
    docker exec -e CHECK_SQL="$1" "$POSTGRES" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -A -F " | " -c "$CHECK_SQL"'
}

printf '\033[1mATS Smart — راستی‌آزمایی حریم خصوصی و رمزنگاری داده‌ها (سرور Production)\033[0m\n' | tee "$REPORT"
printf 'host: %s · %s · %s\n' "$(hostname)" "$(date '+%Y-%m-%d %H:%M:%S')" "$PUBLIC_BASE_URL" | tee -a "$REPORT"

# =============================================================================
section "۰. کلید رمزنگاری — فقط متغیر محیطی محافظت‌شده‌ی سرویس‌های مجاز"
# =============================================================================
mode="$(stat -c '%a' secrets/pii.env 2>/dev/null)"
[[ "$mode" == "600" ]] && pass "secrets/pii.env فقط برای کاربر استقرار خواندنی است (${mode})" || fail "مجوز secrets/pii.env: ${mode:-ناموجود}"
grep -q '^PII_' .env 2>/dev/null && fail "کلید در .env مشترک است" || pass "کلید در .env مشترک (که به همه‌ی سرویس‌ها می‌رسد) نیست"
holders=()
for id in $(docker ps -q --filter "label=com.docker.compose.project=${PROJECT}"); do
    if docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$id" | grep -q '^PII_ENCRYPTION_KEYS='; then
        holders+=("$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id")")
    fi
done
holders_list="$(printf '%s\n' "${holders[@]}" | sort -u | tr '\n' ' ')"
info "کانتینرهای دارای کلید: ${holders_list}"
[[ "$holders_list" == "backend_api worker " ]] && pass "فقط backend_api و worker کلید دارند (gateway، فرانت‌اند، scheduler، مانیتورینگ و backup ندارند)" \
    || fail "کانتینرهای دارای کلید: ${holders_list}"
image="$(docker inspect --format '{{.Config.Image}}' "$API")"
image_keys="$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$image" | grep -c '^PII_' || true)"
[[ "$image_keys" == "0" ]] && pass "ایمیج بک‌اند (${image}) هیچ کلیدی ندارد" || fail "کلید داخل ایمیج است"

# =============================================================================
section "۱. ساخت سازمان و کارجوی آزمایشی (رمزنگاری خودکار هنگام ذخیره)"
# =============================================================================
docker exec -i -e RUN_ID="$RUN_ID" "$API" python - <<'PY' 2>&1 | collect
import asyncio, json, os, secrets
from app.core.security import hash_password
from app.core.tenant_provisioning import provision_tenant
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Job, Resume, StatusHistory, User

RUN_ID = os.environ["RUN_ID"]


async def main():
    password = secrets.token_urlsafe(12) + "9!"
    async with AsyncSessionLocal() as db:
        hr = User(email=f"privacy-hr-{RUN_ID}@example.com", password_hash=hash_password(password), role="HR_Manager")
        tenant = await provision_tenant(db, name=f"Privacy Check {RUN_ID}", owner=hr)
        job = Job(title="Privacy Check Backend", skills_required=["Python"], created_by=hr.id, tenant_id=tenant.id)
        user = User(email=f"privacy-cand-{RUN_ID}@example.com", password_hash=hash_password(password), role="Candidate")
        db.add_all([job, user])
        await db.flush()
        candidate = Candidate(user_id=user.id, first_name="Sara", last_name="Rezaei", phone="09121234567", location="Tehran, Vanak")
        db.add(candidate)
        await db.flush()
        application = Application(job_id=job.id, candidate_id=candidate.id, tenant_id=tenant.id, current_status="Screening", score_ai=82)
        db.add(application)
        await db.flush()
        # قیف استخدام از تاریخچه‌ی وضعیت شمرده می‌شود: Draft ← Applied ← Screening (قیف: Applied=1، Screening=1)
        for old_status, new_status in (("Draft", "Applied"), ("Applied", "Screening")):
            db.add(StatusHistory(application_id=application.id, tenant_id=tenant.id, old_status=old_status,
                                 new_status=new_status, changed_by=hr.id))
        db.add_all([
            Resume(candidate_id=candidate.id, tenant_id=tenant.id, file_url=f"deleted:privacy-check-{RUN_ID}",
                   raw_text="Sara Rezaei 09121234567 — Senior Python Django engineer, Kubernetes",
                   parsed_data={"personal_info": {"name": "Sara Rezaei", "phone": "09121234567"}},
                   skill_analysis={"skills": ["Python"], "total_experience_years": 5}),
        ])
        await db.commit()
        print("کارجو: Sara Rezaei · 09121234567 · Tehran, Vanak (فقط داخل برنامه، رمزشده ذخیره شد)")
        print("STATE " + json.dumps({"password": password, "hr": hr.email, "candidate_email": user.email,
                                     "candidate_id": str(candidate.id), "user_id": str(user.id)}))
        print("RESULT PASS سازمان، آگهی، درخواست و رزومه‌ی آزمایشی ساخته شد")

asyncio.run(main())
PY
CANDIDATE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["candidate_id"])' "$STATE" 2>/dev/null)"
[[ -n "$CANDIDATE_ID" ]] || { fail "ساخت داده‌ی آزمایشی ناموفق بود"; exit 1; }

# =============================================================================
section "۲. بازرسی مستقیم دیتابیس (مثل DBeaver) — متن رمزشده، ناخوانا"
# =============================================================================
raw="$(psql_raw "SELECT left(first_name, 40) AS first_name, left(phone, 40) AS phone, left(location, 40) AS location FROM candidates WHERE id = '${CANDIDATE_ID}'; SELECT left(raw_text, 60) AS raw_text, left(parsed_data, 40) AS parsed_data, cardinality(search_tokens) AS search_tokens FROM resumes WHERE candidate_id = '${CANDIDATE_ID}';")"
printf '%s\n' "$raw" | while IFS= read -r line; do info "$line"; done
encrypted_count="$(printf '%s\n' "$raw" | grep -o 'gAAAAA' | wc -l)"
[[ "$encrypted_count" -ge 5 ]] && pass "نام، تلفن، آدرس، متن خام و داده‌ی استخراج‌شده‌ی رزومه در دیتابیس متن رمزشده‌ی Fernet (gAAAAA…) هستند" \
    || fail "ستون رمزنشده پیدا شد"
printf '%s\n' "$raw" | grep -qiE 'Sara|Rezaei|0912|Tehran|Python|Kubernetes' && fail "متن خوانا در دیتابیس پیدا شد" \
    || pass "هیچ‌کدام از «Sara، 0912…، Tehran، Python» در خروجی خام دیتابیس نیست"

# =============================================================================
section "۳. همان رکورد از API برای کارشناس HR مجاز (رمزگشایی خودکار) و حذف حساب کارجو"
# =============================================================================
CHECK_BASE="$PUBLIC_BASE_URL" CHECK_STATE="$STATE" python3 - <<'PY' 2>&1 | collect
import json, os, urllib.error, urllib.parse, urllib.request

BASE = os.environ["CHECK_BASE"].rstrip("/") + "/api/v1"
state = json.load(open(os.environ["CHECK_STATE"]))


def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json", "User-Agent": "privacy-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, method=method, headers=headers), timeout=20) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


def result(ok, text):
    print(f"RESULT {'PASS' if ok else 'FAIL'} {text}")


_, hr = call("POST", "/auth/login", body={"email": state["hr"], "password": state["password"]})
_, cand = call("POST", "/auth/login", body={"email": state["candidate_email"], "password": state["password"]})
if not (hr and cand):
    result(False, "ورود کاربران آزمایشی ناموفق بود")
    raise SystemExit
hr_token, cand_token = hr["access_token"], cand["access_token"]

code, found = call("GET", "/candidates/search/?" + urllib.parse.urlencode({"q": "python AND kubernetes"}), hr_token)
item = next((i for i in (found or {}).get("items", []) if i["candidate_id"] == state["candidate_id"]), None)
if item:
    print(f"API ← {item['first_name']} {item['last_name']} · {item['phone']} · {item['location']}")
result(bool(item) and item["phone"] == "09121234567", "HR همان رکورد را خوانا می‌بیند و جستجوی «python AND kubernetes» روی ایندکس کور پیدایش می‌کند")

_, funnel_before = call("GET", "/analytics/funnel", hr_token)
code, deleted = call("DELETE", "/candidates/me/", cand_token)
result(code == 200, f"DELETE /api/v1/candidates/me/ → {code}")
_, funnel_after = call("GET", "/analytics/funnel", hr_token)
stages = lambda funnel: {s["stage"]: s["count"] for s in (funnel or {}).get("stages", [])}
print(f"قیف قبل: {stages(funnel_before)}")
print(f"قیف بعد: {stages(funnel_after)}")
result(stages(funnel_before).get("Screening") == 1 and stages(funnel_before) == stages(funnel_after),
       "قیف استخدام سازمان (Applied=1، Screening=1) قبل و بعد از حذف حساب دقیقاً یکی است")
code, _ = call("GET", "/candidates/me", cand_token)
result(code == 401, f"توکن کارجوی حذف‌شده → {code}")
code, _ = call("POST", "/auth/login", body={"email": state["candidate_email"], "password": state["password"]})
result(code == 401, f"ورود دوباره با ایمیل قبلی → {code}")
PY

raw="$(psql_raw "SELECT left(first_name, 20) AS first_name, phone, location, (SELECT email FROM users WHERE users.id = candidates.user_id) AS email FROM candidates WHERE id = '${CANDIDATE_ID}'; SELECT file_url, raw_text, parsed_data, search_tokens FROM resumes WHERE candidate_id = '${CANDIDATE_ID}'; SELECT current_status, score_ai FROM applications WHERE candidate_id = '${CANDIDATE_ID}';")"
printf '%s\n' "$raw" | while IFS= read -r line; do info "$line"; done
printf '%s\n' "$raw" | grep -q 'deleted-.*@anonymized.invalid' && printf '%s\n' "$raw" | grep -q 'Screening | 82' \
    && pass "ردیف‌ها حذف نشده‌اند: ایمیل ناشناس، تلفن/آدرس/متن رزومه NULL، درخواست (Screening، نمره ۸۲) سر جایش" \
    || fail "وضعیت ناشناس‌سازی در دیتابیس"

# =============================================================================
section "پاک‌سازی سازمان و کاربران آزمایشی"
# =============================================================================
docker exec -i -e RUN_ID="$RUN_ID" "$API" python - <<'PY' 2>&1 | collect
import asyncio, os
from sqlalchemy import delete, or_, select
from app.core.redis_client import close_redis_connection
from app.core.sessions import SessionStoreUnavailable, revoke_all_sessions
from app.core.tenant_provisioning import delete_owned_tenants
from app.db.session import AsyncSessionLocal
from app.models import Application, Candidate, Company, Job, Resume, StatusHistory, User

RUN_ID = os.environ["RUN_ID"]


async def main():
    async with AsyncSessionLocal() as db:
        tenant_ids = (await db.execute(select(Company.id).where(Company.name == f"Privacy Check {RUN_ID}"))).scalars().all()
        app_ids = (await db.execute(select(Application.id).where(Application.tenant_id.in_(tenant_ids)))).scalars().all()
        candidate_ids = (await db.execute(select(Application.candidate_id).where(Application.id.in_(app_ids)))).scalars().all()
        user_ids = (await db.execute(select(Candidate.user_id).where(Candidate.id.in_(candidate_ids)))).scalars().all()
        owner_ids = (await db.execute(select(Company.owner_id).where(Company.id.in_(tenant_ids)))).scalars().all()
        for user_id in [*user_ids, *owner_ids]:
            try:
                await revoke_all_sessions(str(user_id))
            except SessionStoreUnavailable:
                print("هشدار: Redis در دسترس نبود؛ نشست‌های آزمایشی با پایان TTL خودشان پاک می‌شوند")
        await db.execute(delete(StatusHistory).where(StatusHistory.application_id.in_(app_ids)))
        await db.execute(delete(Application).where(Application.id.in_(app_ids)))
        await db.execute(delete(Resume).where(Resume.candidate_id.in_(candidate_ids)))
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(delete(Job).where(Job.tenant_id.in_(tenant_ids)))
        await delete_owned_tenants(db, owner_ids)
        await db.execute(delete(User).where(or_(User.id.in_(user_ids), User.id.in_(owner_ids))))
        await db.commit()
        print(f"RESULT PASS سازمان آزمایشی، {len(user_ids) + len(owner_ids)} کاربر و رکوردهایشان پاک شد")
    await close_redis_connection()

asyncio.run(main())
PY

printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED" | tee -a "$REPORT"
info "گزارش کامل: ${PROJECT_DIR}/${REPORT}"
if ((FAILED == 0)); then
    printf '\033[1;32m[PRIVACY PASS] داده‌های شخصی در دیتابیس رمزشده‌اند، حذف حساب ناشناس‌سازی می‌کند و آمار استخدام سالم می‌ماند\033[0m\n' | tee -a "$REPORT"
    exit 0
fi
printf '\033[1;31m[PRIVACY FAIL]\033[0m\n' | tee -a "$REPORT"
exit 1
