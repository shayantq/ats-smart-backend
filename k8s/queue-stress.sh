#!/usr/bin/env bash
# =============================================================================
# تست استرس صف‌های پس‌زمینه (Redis / RQ): ایمیل انبوه + پردازش سنگین رزومه، هم‌زمان
#
#   bash k8s/queue-stress.sh                         پیش‌فرض: ۳۰۰۰ ایمیل انبوه + ۴۰ رزومه‌ی واقعی
#   BULK_EMAILS=10000 RESUMES=100 bash k8s/queue-stress.sh
#   KEEP_DATA=1 ...                                  داده‌ها و ایمیل‌های آزمایشی پس از تست پاک نشوند
#
# سناریو (همه از مسیر واقعی برنامه):
#   ۱. ۴۰ کارجوی آزمایشی رزومه‌ی PDF واقعی آپلود می‌کنند (POST /api/v1/resumes/upload) ← صف resumes
#   ۲. هم‌زمان ۳۰۰۰ ایمیل اطلاع‌رسانی انبوه با enqueue_bulk به صف bulk اضافه می‌شود
#   ۳. وسط شلوغی، یک ایمیل فوری OTP (صف notifications) فرستاده و زمان رسیدنش سنجیده می‌شود
#   ۴. یک Pod از هر Worker وسط کار حذف می‌شود (مثل Scale Down یا استقرار نسخه‌ی جدید)
#
# معیارها:
#   - هیچ کاری از دست نرود: همه‌ی ایمیل‌ها به سرور SMTP (Mailpit) برسند، همه‌ی رزومه‌ها پردازش شوند، صفر کار ناموفق
#   - سیستم مختل نشود: API در حین پردازش پاسخگو بماند و هیچ Pod ی ری‌استارت/OOM نشود
#   - اولویت: OTP پشت هزاران ایمیل انبوه منتظر نماند
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

if grep -qi microsoft /proc/version 2>/dev/null && command -v kubectl.exe >/dev/null 2>&1; then
    kubectl() { kubectl.exe "$@"; }
fi
command -v kubectl >/dev/null 2>&1 || { echo "kubectl پیدا نشد" >&2; exit 2; }

cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-ats-smart}"
BULK_EMAILS="${BULK_EMAILS:-3000}"
RESUMES="${RESUMES:-40}"
DRAIN_TIMEOUT="${DRAIN_TIMEOUT:-900}"
RUN_ID="$(date +%Y%m%d%H%M%S)"
REPORT_DIR="k8s/loadtest/reports"
REPORT="${REPORT_DIR}/queue-stress-${RUN_ID}.log"
mkdir -p "$REPORT_DIR"

PASSED=0
FAILED=0
section() { printf '\n\033[1;34m━━━ %s ━━━\033[0m\n' "$*" | tee -a "$REPORT"; }
pass() { PASSED=$((PASSED + 1)); printf '  \033[32m✔ PASS\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
fail() { FAILED=$((FAILED + 1)); printf '  \033[31m✘ FAIL\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
info() { printf '          %s\n' "$*" | tee -a "$REPORT"; }
k() { kubectl -n "$NAMESPACE" "$@"; }

PYTHON=""
for candidate in python3 python; do
    if "$candidate" -c "import json" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
[[ -n "$PYTHON" ]] || { echo "Python روی این سیستم پیدا نشد" >&2; exit 2; }
json_get() { "$PYTHON" -c "import json, sys; print(json.loads(sys.argv[1])$2)" "$1" 2>/dev/null; }

# اجرای پایتون داخل Pod بک‌اند (همان کد، تنظیمات و دسترسی‌های برنامه) — اسکریپت از stdin
in_backend() { k exec -i deploy/backend-api -c backend-api -- env RUN_ID="$RUN_ID" "$@" python -; }

# وضعیت لحظه‌ای صف‌ها (مستقیم از Redis) + تعداد ایمیل‌های رسیده به Mailpit — یک JSON
snapshot() {
    in_backend <<'PY'
import json, urllib.request
from rq import Queue
from rq.registry import FailedJobRegistry, StartedJobRegistry
from app.core.queue import ALL_QUEUES, _get_sync_redis_client

connection = _get_sync_redis_client()
state = {}
for name in ALL_QUEUES:
    queue = Queue(name, connection=connection)
    state[name] = {
        "queued": queue.count,
        "started": StartedJobRegistry(queue=queue).count,
        "failed": FailedJobRegistry(queue=queue).count,
    }
with urllib.request.urlopen("http://mailpit:8025/api/v1/messages?limit=1", timeout=5) as response:
    state["mailpit"] = json.load(response)["total"]
print(json.dumps(state))
PY
}

printf '\033[1mATS Smart — تست استرس صف‌های Redis (ایمیل انبوه + پردازش رزومه)\033[0m\n' | tee "$REPORT"
printf 'context: %s · %s · %s ایمیل انبوه + %s رزومه\n' "$(kubectl config current-context)" "$(date '+%Y-%m-%d %H:%M:%S')" \
    "$BULK_EMAILS" "$RESUMES" | tee -a "$REPORT"

# =============================================================================
section "پیش‌نیازها"
# =============================================================================
if ! k get svc mailpit >/dev/null 2>&1; then
    fail "سرور SMTP آزمایشی (Mailpit) در این Namespace نیست — تست ایمیل انبوه فقط روی Overlay لوکال اجرا می‌شود"
    exit 1
fi
pass "Mailpit (SMTP آزمایشی) آماده است — هیچ ایمیلی بیرون نمی‌رود"
for deployment in worker resume-worker redis; do
    info "${deployment}: $(k get deploy "$deployment" -o jsonpath='{.status.readyReplicas}') Pod آماده"
done
info "Redis: $(k exec deploy/redis -c redis -- redis-cli CONFIG GET maxmemory-policy | tr '\n' ' ')· $(k exec deploy/redis -c redis -- redis-cli CONFIG GET appendfsync | tr '\n' ' ')"
restarts_before="$(k get pods -o jsonpath='{range .items[*]}{range .status.containerStatuses[*]}{.restartCount}{"\n"}{end}{end}' | awk '{s += $1} END {print s + 0}')"
# صندوق Mailpit خالی می‌شود تا شمارش ایمیل‌های این تست دقیق باشد
in_backend <<'PY' >/dev/null
import urllib.request
urllib.request.urlopen(urllib.request.Request("http://mailpit:8025/api/v1/messages", method="DELETE"), timeout=10)
PY
before="$(snapshot)"
failed_before="$("$PYTHON" -c "import json, sys; s = json.loads(sys.argv[1]); print(sum(v['failed'] for k, v in s.items() if k != 'mailpit'))" "$before")"
info "صف‌ها پیش از تست: ${before}"

# =============================================================================
section "پاسخ‌دهی API پیش از تست (مبنا)"
# =============================================================================
api_probe() {  # <seconds> → JSON آمار زمان پاسخ GET /api/v1/jobs/ از مسیر Ingress
    in_backend PROBE_SECONDS="$1" <<'PY'
import json, os, statistics, time, urllib.request

url = "http://nginx-ingress.nginx-ingress.svc.cluster.local:8081/api/v1/jobs/?limit=20"
deadline, timings, errors = time.monotonic() + int(os.environ["PROBE_SECONDS"]), [], 0
while time.monotonic() < deadline:
    started = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"Host": "localhost"})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        timings.append((time.monotonic() - started) * 1000)
    except Exception:
        errors += 1
    time.sleep(0.2)
timings.sort()
p95 = timings[int(len(timings) * 0.95) - 1] if timings else 0
print(json.dumps({"count": len(timings), "errors": errors, "p50": round(statistics.median(timings), 1) if timings else 0,
                  "p95": round(p95, 1), "max": round(max(timings), 1) if timings else 0}))
PY
}
baseline="$(api_probe 15)"
info "مبنا (۱۵ ثانیه، بدون بار صف): ${baseline}"

# =============================================================================
section "ایجاد بار: ${RESUMES} آپلود رزومه‌ی واقعی + ${BULK_EMAILS} ایمیل انبوه"
# =============================================================================
pdf_b64="$("$PYTHON" -c "import base64, sys; print(base64.b64encode(open(sys.argv[1], 'rb').read()).decode())" loadtest/sample_resume.pdf)"
load_started=$SECONDS
load="$(in_backend RESUMES="$RESUMES" BULK_EMAILS="$BULK_EMAILS" PDF_B64="$pdf_b64" <<'PY' 2>&1
import asyncio, base64, os, time

import httpx

from app.core.queue import enqueue_bulk
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.models import Job, User
from app.tasks.notifications import send_status_update_email_task

RUN = os.environ["RUN_ID"]
PDF = base64.b64decode(os.environ["PDF_B64"])


async def main() -> None:
    async with AsyncSessionLocal() as session:
        hr = User(email=f"qstress-hr-{RUN}@example.com", password_hash="!", role="HR_Manager")
        session.add(hr)
        await session.flush()
        job = Job(
            created_by=hr.id, title=f"[QueueStress {RUN}] برنامه‌نویس ارشد بک‌اند", department="فنی",
            description="Python FastAPI PostgreSQL Docker Kubernetes", skills_required=["Python", "FastAPI", "Docker"],
            status="Active", required_seniority="Senior", location="تهران",
        )
        candidates = [
            User(email=f"qstress-cand-{RUN}-{index}@example.com", password_hash="!", role="Candidate")
            for index in range(int(os.environ["RESUMES"]))
        ]
        session.add(job)
        session.add_all(candidates)
        await session.commit()
        job_id, candidate_ids = str(job.id), [str(user.id) for user in candidates]

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30) as client:
        async def upload(user_id: str) -> int:
            token, _ = create_access_token(user_id)
            response = await client.post(
                "/api/v1/resumes/upload", data={"job_id": job_id},
                files={"file": ("resume.pdf", PDF, "application/pdf")}, headers={"Authorization": f"Bearer {token}"},
            )
            return response.status_code

        started = time.monotonic()
        codes = await asyncio.gather(*(upload(user_id) for user_id in candidate_ids))
        print(f"UPLOADS {sum(code == 202 for code in codes)} {round(time.monotonic() - started, 1)}")

    recipients = [
        (f"qbulk-{RUN}-{index}@example.com", f"کارجوی {index}", "برنامه‌نویس ارشد بک‌اند", "Screening")
        for index in range(int(os.environ["BULK_EMAILS"]))
    ]
    started = time.monotonic()
    count = await enqueue_bulk(send_status_update_email_task, recipients)
    print(f"BULK {count} {round(time.monotonic() - started, 2)}")
    print(f"JOB {job_id}")


asyncio.run(main())
PY
)"
uploads="$(grep -oE "^UPLOADS [0-9]+ [0-9.]+" <<<"$load")"
bulk="$(grep -oE "^BULK [0-9]+ [0-9.]+" <<<"$load")"
job_id="$(grep -oE "^JOB [0-9a-f-]+" <<<"$load" | cut -d' ' -f2)"
[[ "$(cut -d' ' -f2 <<<"$uploads")" == "$RESUMES" ]] \
    && pass "${RESUMES} رزومه با پاسخ 202 آپلود شد در $(cut -d' ' -f3 <<<"$uploads") ثانیه (پاسخ فوری؛ پردازش در صف resumes)" \
    || { fail "آپلود رزومه‌ها: ${load}"; exit 1; }
[[ "$(cut -d' ' -f2 <<<"$bulk")" == "$BULK_EMAILS" ]] \
    && pass "${BULK_EMAILS} ایمیل انبوه در $(cut -d' ' -f3 <<<"$bulk") ثانیه به صف bulk اضافه شد (Pipeline های ۵۰۰تایی)" \
    || { fail "افزودن ایمیل‌های انبوه: ${load}"; exit 1; }

# پاسخ‌دهی API در حین پردازش صف — هم‌زمان در پس‌زمینه
probe_file="$(mktemp)"
api_probe 90 >"$probe_file" 2>&1 &
probe_pid=$!

# =============================================================================
section "پردازش صف‌ها (هر ۵ ثانیه) — ایمیل فوری OTP و حذف Pod های Worker وسط کار"
# =============================================================================
printf '\n  %-7s %-24s %-22s %-16s %-10s %-10s\n' TIME "NOTIF/BULK/RESUME queued" "STARTED (all queues)" "MAILPIT" WORKER RESUME-W | tee -a "$REPORT"
otp_sent=""
otp_latency=""
killed=0
peak_bulk=0
while true; do
    elapsed=$((SECONDS - load_started))
    state="$(snapshot)"
    read -r q_notif q_bulk q_resume started delivered <<<"$("$PYTHON" -c "
import json, sys
s = json.loads(sys.argv[1])
print(s['notifications']['queued'], s['bulk']['queued'], s['resumes']['queued'],
      sum(v['started'] for k, v in s.items() if k != 'mailpit'), s['mailpit'])" "$state" 2>/dev/null)"
    ((q_bulk > peak_bulk)) && peak_bulk=$q_bulk
    printf '  %-7s %-24s %-22s %-16s %-10s %-10s\n' "$(printf '%02d:%02d' $((elapsed / 60)) $((elapsed % 60)))" \
        "${q_notif}/${q_bulk}/${q_resume}" "$started" "${delivered}/$((BULK_EMAILS + 1))" \
        "$(k get deploy worker -o jsonpath='{.status.readyReplicas}')" "$(k get deploy resume-worker -o jsonpath='{.status.readyReplicas}')" | tee -a "$REPORT"

    # ایمیل فوری وسط صف شلوغ ایمیل‌های انبوه: باید بدون انتظار پشت آن‌ها برسد
    if [[ -z "$otp_sent" && "$q_bulk" -gt 500 ]]; then
        otp_sent="$(date +%s)"
        otp_backlog=$q_bulk
        in_backend <<'PY' >/dev/null
import asyncio, os
from app.core.queue import enqueue_task
from app.tasks.notifications import send_otp_email_task
asyncio.run(enqueue_task(send_otp_email_task, f"qotp-{os.environ['RUN_ID']}@example.com", "482913", 10))
PY
        info "ایمیل OTP به صف notifications اضافه شد (${otp_backlog} ایمیل انبوه جلوتر در صف)"
    fi
    if [[ -n "$otp_sent" && -z "$otp_latency" ]]; then
        found="$(in_backend <<'PY'
import json, os, urllib.parse, urllib.request
query = urllib.parse.quote(f"to:qotp-{os.environ['RUN_ID']}@example.com")
with urllib.request.urlopen(f"http://mailpit:8025/api/v1/search?query={query}", timeout=5) as response:
    print(json.load(response)["messages_count"])
PY
)"
        [[ "$found" == "1" ]] && otp_latency=$(($(date +%s) - otp_sent)) && info "OTP پس از ${otp_latency} ثانیه به صندوق رسید (صف انبوه هنوز ${q_bulk} ایمیل منتظر داشت)"
    fi

    # Scale Down / استقرار وسط کار: حذف عادی (SIGTERM) یک Pod از هر Worker
    if ((killed == 0 && elapsed > 20 && q_bulk > 0)); then
        for deployment in worker resume-worker; do
            pod="$(k get pods -l "app.kubernetes.io/name=${deployment}" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')"
            [[ -n "$pod" ]] && k delete pod "$pod" --wait=false >/dev/null && info "Pod ${pod} وسط کار حذف شد (SIGTERM — مثل Scale Down یا استقرار)"
        done
        killed=1
    fi

    if [[ "$q_notif" == "0" && "$q_bulk" == "0" && "$q_resume" == "0" && "$started" == "0" && -n "$otp_latency" ]]; then
        drain_seconds=$elapsed
        break
    fi
    if ((elapsed > DRAIN_TIMEOUT)); then
        drain_seconds=""
        break
    fi
    sleep 5
done
wait "$probe_pid" 2>/dev/null
during="$(cat "$probe_file")"
rm -f "$probe_file"
sleep 3
after="$(snapshot)"

# =============================================================================
section "معیار: هیچ کاری از دست نرفت"
# =============================================================================
delivered="$(json_get "$after" "['mailpit']")"
failed_after="$("$PYTHON" -c "import json, sys; s = json.loads(sys.argv[1]); print(sum(v['failed'] for k, v in s.items() if k != 'mailpit'))" "$after")"
if [[ -n "${drain_seconds:-}" ]]; then
    pass "همه‌ی صف‌ها در ${drain_seconds} ثانیه خالی شدند (اوج صف انبوه: ${peak_bulk})"
else
    fail "صف‌ها در ${DRAIN_TIMEOUT} ثانیه خالی نشدند: ${after}"
fi
[[ "$delivered" == "$((BULK_EMAILS + 1))" ]] \
    && pass "همه‌ی $((BULK_EMAILS + 1)) ایمیل (${BULK_EMAILS} انبوه + ۱ OTP) به سرور SMTP رسیدند — حتی با حذف Pod های Worker وسط کار" \
    || fail "ایمیل‌های رسیده: ${delivered} از $((BULK_EMAILS + 1))"
((failed_after == failed_before)) && pass "صفر کار ناموفق جدید در صف‌ها" || fail "$((failed_after - failed_before)) کار ناموفق جدید"
processed="$(printf '%s\n' "select count(*) from applications a join resumes r on r.candidate_id = a.candidate_id where a.job_id = '${job_id}' and a.score_ai is not null and r.raw_text is not null and r.skill_analysis is not null;" \
    | k exec -i postgres-0 -c postgres -- sh -c 'psql -X -At -U "$POSTGRES_USER" -d smart_ats_db')"
[[ "$processed" == "$RESUMES" ]] \
    && pass "همه‌ی ${RESUMES} رزومه کامل پردازش شدند (متن، تحلیل مهارت و نمره‌ی تطابق ثبت شد)" \
    || fail "رزومه‌های پردازش‌شده: ${processed} از ${RESUMES}"

# =============================================================================
section "معیار: سیستم مختل نشد و ایمیل فوری معطل نماند"
# =============================================================================
info "API پیش از بار:      ${baseline}"
info "API حین پردازش صف:  ${during}"
during_errors="$(json_get "$during" "['errors']")"
during_p95="$(json_get "$during" "['p95']")"
[[ "$during_errors" == "0" ]] && "$PYTHON" -c "import sys; sys.exit(0 if float(sys.argv[1]) < 1000 else 1)" "${during_p95:-99999}" \
    && pass "API در تمام مدت پردازش پاسخگو بود — ۰ خطا، p95 = ${during_p95}ms" \
    || fail "اختلال API حین پردازش صف: ${during}"
if [[ -n "$otp_latency" ]] && ((otp_latency <= 30)); then
    pass "ایمیل OTP پشت ${otp_backlog} ایمیل انبوه منتظر نماند — رسید در ${otp_latency} ثانیه (صف پراولویت notifications)"
else
    fail "زمان رسیدن OTP: ${otp_latency:-نرسید} ثانیه"
fi
restarts_after="$(k get pods -o jsonpath='{range .items[*]}{range .status.containerStatuses[*]}{.restartCount}{"\n"}{end}{end}' | awk '{s += $1} END {print s + 0}')"
((restarts_after == restarts_before)) && pass "هیچ Pod ی ری‌استارت یا OOM نشد" || fail "$((restarts_after - restarts_before)) ری‌استارت کانتینر حین تست"
info "حافظه‌ی Redis پس از تست: $(k exec deploy/redis -c redis -- redis-cli INFO memory | grep -E '^used_memory_human' | tr -d '\r')"
k get hpa worker resume-worker 2>/dev/null | sed 's/^/  /' | tee -a "$REPORT"

# =============================================================================
section "پاک‌سازی"
# =============================================================================
if [[ "${KEEP_DATA:-0}" != "1" ]]; then
    in_backend <<'PY' >/dev/null 2>&1
import asyncio, os, urllib.request
from sqlalchemy import text
from app.core.storage import resolve_local_media_path
from app.db.session import AsyncSessionLocal

RUN = os.environ["RUN_ID"]
USERS = f"(select id from users where email like 'qstress-%-{RUN}%@example.com')"
CANDIDATES = f"(select id from candidates where user_id in {USERS})"
APPLICATIONS = f"(select id from applications where candidate_id in {CANDIDATES})"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        files = (await session.execute(text(f"select file_url from resumes where candidate_id in {CANDIDATES}"))).scalars()
        for file_url in files:
            path = resolve_local_media_path(file_url)
            if path is not None:
                path.unlink(missing_ok=True)
        for statement in (
            f"delete from status_history where application_id in {APPLICATIONS}",
            f"delete from applications where candidate_id in {CANDIDATES}",
            f"delete from resumes where candidate_id in {CANDIDATES}",
            f"delete from candidates where user_id in {USERS}",
            f"delete from jobs where title like '[QueueStress {RUN}]%'",
            f"delete from users where email like 'qstress-%-{RUN}%@example.com'",
        ):
            await session.execute(text(statement))
        await session.commit()
    urllib.request.urlopen(urllib.request.Request("http://mailpit:8025/api/v1/messages", method="DELETE"), timeout=10)


asyncio.run(main())
PY
    info "کاربران، آگهی، رزومه‌ها، فایل‌ها و ایمیل‌های آزمایشی حذف شدند (KEEP_DATA=1 برای نگه‌داشتن)"
fi
info "گزارش کامل: ${REPORT}"

printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED" | tee -a "$REPORT"
if ((FAILED == 0)); then
    printf '\033[1;32m[QUEUE STRESS PASS] هیچ کاری از دست نرفت و سیستم مختل نشد\033[0m\n' | tee -a "$REPORT"
    exit 0
fi
printf '\033[1;31m[QUEUE STRESS FAIL]\033[0m\n' | tee -a "$REPORT"
exit 1
