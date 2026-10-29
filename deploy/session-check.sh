#!/usr/bin/env bash
# =============================================================================
# راستی‌آزمایی مدیریت نشست‌ها روی سرور Production — فقط با یک کاربر آزمایشی موقت که در پایان پاک می‌شود:
#
#   cd /opt/ats-smart && bash deploy/session-check.sh
#
#   ۱. ورود یک کاربر از دو «دستگاه» (Chrome/Windows و Safari/iPhone) از مسیر واقعی اینترنت (دامنه → Caddy
#      → Gateway → API) و فهرست نشست‌ها با جزئیات مرورگر، IP واقعی و آخرین فعالیت
#   ۲. ابطال نشست دستگاه دوم از دستگاه اول ← jti در فهرست سیاه Redis، نوسازی آن دستگاه ← 401
#   ۳. کار ایمیل هشدار «ورود از دستگاه جدید» در صف Redis (RQ)
#   ۴. موتور تشخیص ورود مشکوک با دیتابیس GeoIP واقعی سرور (تهران ← آلمان در ۳۰ دقیقه)
# =============================================================================
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

RUN_ID="$(date +%Y%m%d%H%M%S)"
REPORT_DIR="${REPORT_DIR:-reports}"
REPORT="${REPORT_DIR}/sessions-${RUN_ID}.log"
mkdir -p "${REPORT_DIR}"
PASSED=0
FAILED=0

section() { printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$*" | tee -a "$REPORT"; }
pass() { PASSED=$((PASSED + 1)); printf '  \033[32m✔ PASS\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
fail() { FAILED=$((FAILED + 1)); printf '  \033[31m✘ FAIL\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
info() { printf '          %s\n' "$*" | tee -a "$REPORT"; }
collect() {  # خطوط «RESULT PASS|FAIL ...» خروجی پایتون → شمارنده‌ها
    while IFS= read -r line; do
        case "$line" in
            "RESULT PASS "*) pass "${line#RESULT PASS }" ;;
            "RESULT FAIL "*) fail "${line#RESULT FAIL }" ;;
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
REDIS="$(container redis_cache)"
PUBLIC_BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env 2>/dev/null | cut -d= -f2-)"
[[ -n "$API" && -n "$REDIS" && -n "$PUBLIC_BASE_URL" ]] || { echo "API/Redis بالا نیستند یا PUBLIC_BASE_URL در .env نیست" >&2; exit 2; }

EMAIL="session-check-${RUN_ID}@example.com"
PASSWORD="Chk-$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 12)-9"
STATE="$(mktemp)"
trap 'rm -f "$STATE"' EXIT

printf '\033[1mATS Smart — راستی‌آزمایی مدیریت نشست‌ها (سرور Production)\033[0m\n' | tee "$REPORT"
printf 'host: %s · %s · %s · کاربر آزمایشی: %s\n' "$(hostname)" "$(date '+%Y-%m-%d %H:%M:%S')" "$PUBLIC_BASE_URL" "$EMAIL" | tee -a "$REPORT"

cleanup() {
    section "پاک‌سازی کاربر آزمایشی"
    docker exec -i -e CHECK_EMAIL="$EMAIL" "$API" python - <<'PY' 2>&1 | collect
import asyncio, os
from sqlalchemy import delete, select
from app.core.redis_client import get_redis_client
from app.core.sessions import revoke_all_sessions
from app.db.session import AsyncSessionLocal
from app.models import User

async def main():
    email = os.environ["CHECK_EMAIL"]
    async with AsyncSessionLocal() as db:
        user_id = (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
        if user_id is None:
            print("RESULT PASS کاربری برای پاک‌سازی نبود")
            return
        revoked = await revoke_all_sessions(str(user_id))
        await get_redis_client().delete(f"user_known_devices:{user_id}", f"user_login_history:{user_id}")
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
        print(f"RESULT PASS کاربر آزمایشی، {revoked} نشست باقی‌مانده و سابقه‌ی ورودش پاک شد")

asyncio.run(main())
PY
}

# =============================================================================
section "۱. ورود از دو دستگاه و فهرست نشست‌ها — از مسیر واقعی اینترنت"
# =============================================================================
CHECK_BASE="$PUBLIC_BASE_URL" CHECK_EMAIL="$EMAIL" CHECK_PASSWORD="$PASSWORD" CHECK_STATE="$STATE" python3 - <<'PY' 2>&1 | collect
import json, os, urllib.error, urllib.request

BASE = os.environ["CHECK_BASE"].rstrip("/") + "/api/v1/auth"
EMAIL, PASSWORD = os.environ["CHECK_EMAIL"], os.environ["CHECK_PASSWORD"]
LAPTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
PHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
         "Version/17.5 Mobile/15E148 Safari/604.1")


def call(method, path, user_agent=LAPTOP, token=None, body=None):
    headers = {"User-Agent": user_agent, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


def result(ok, text):
    print(f"RESULT {'PASS' if ok else 'FAIL'} {text}")


code, _ = call("POST", "/register", body={"email": EMAIL, "password": PASSWORD, "role": "Candidate"})
result(code == 201, f"ثبت‌نام کاربر آزمایشی → {code}")
code, laptop = call("POST", "/login", LAPTOP, body={"email": EMAIL, "password": PASSWORD})
result(code == 200, f"ورود دستگاه ۱ (Chrome · Windows) → {code}")
code, phone = call("POST", "/login", PHONE, body={"email": EMAIL, "password": PASSWORD})
result(code == 200, f"ورود دستگاه ۲ (Safari · iPhone) → {code}")
if not (laptop and phone):
    raise SystemExit

code, listed = call("GET", "/sessions/", LAPTOP, laptop["access_token"])
items = (listed or {}).get("items", [])
for item in items:
    location = item["location"] or {}
    print(f"{'*' if item['is_current'] else ' '} {item['browser']} {item['browser_version']} · {item['os']} {item['os_version']}"
          f" · {item['device_type']} · IP {item['ip']} · {location.get('city') or '-'} {location.get('country_code') or ''}"
          f" · آخرین فعالیت {item['last_active_at'][:19]}Z")
result(code == 200 and len(items) == 2 and all(i["browser"] and i["os"] and i["last_active_at"] for i in items),
       f"GET /auth/sessions/ → {code}: {len(items)} نشست با مرورگر، سیستم‌عامل، دستگاه و آخرین فعالیت")
current = next((i for i in items if i["is_current"]), None)
result(current is not None and not current["ip"].startswith(("127.", "10.", "172.", "192.168.")),
       f"IP واقعی کاربر (نه IP داخلی Proxy) ثبت شده: {current and current['ip']}")

other = next((i for i in items if not i["is_current"]), None)
json.dump({"laptop": laptop, "phone": phone, "phone_session": other and other["id"]}, open(os.environ["CHECK_STATE"], "w"))
PY

# =============================================================================
section "۲. ابطال نشست دستگاه دوم ← فهرست سیاه Redis و 401 هنگام نوسازی"
# =============================================================================
CHECK_BASE="$PUBLIC_BASE_URL" CHECK_STATE="$STATE" python3 - <<'PY' 2>&1 | collect
import base64, json, os, urllib.error, urllib.request

BASE = os.environ["CHECK_BASE"].rstrip("/") + "/api/v1/auth"
state = json.load(open(os.environ["CHECK_STATE"]))


def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json", "User-Agent": "session-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, method=method, headers=headers), timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as error:
        return error.code


def claims(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


phone_claims = claims(state["phone"]["refresh_token"])
code = call("DELETE", f"/sessions/{state['phone_session']}/", state["laptop"]["access_token"])
print(f"RESULT {'PASS' if code == 204 else 'FAIL'} DELETE /auth/sessions/{state['phone_session']}/ از دستگاه ۱ → {code}")
code = call("POST", "/refresh", body={"refresh_token": state["phone"]["refresh_token"]})
print(f"RESULT {'PASS' if code == 401 else 'FAIL'} نوسازی توکن دستگاه ابطال‌شده → {code} (فرانت‌اند به صفحه‌ی ورود می‌برد)")
code = call("GET", "/me", state["phone"]["access_token"])
print(f"RESULT {'PASS' if code == 401 else 'FAIL'} access_token همان دستگاه، پیش از انقضا → {code}")
code = call("GET", "/me", state["laptop"]["access_token"])
print(f"RESULT {'PASS' if code == 200 else 'FAIL'} دستگاه ۱ همچنان وارد است → {code}")
print(f"JTI {phone_claims['jti']}")
PY
JTI="$(grep -o 'JTI [0-9a-f]*' "$REPORT" | tail -n 1 | cut -d' ' -f2)"
if [[ -n "$JTI" ]]; then
    blacklisted="$(docker exec "$REDIS" redis-cli GET "revoked_refresh:${JTI}" 2>/dev/null)"
    ttl="$(docker exec "$REDIS" redis-cli TTL "revoked_refresh:${JTI}" 2>/dev/null)"
    [[ "$blacklisted" == "revoked" && "${ttl:-0}" -gt 0 ]] \
        && pass "Redis: revoked_refresh:${JTI:0:12}… = ${blacklisted} (TTL ${ttl} ثانیه — تا پایان عمر توکن)" \
        || fail "jti در فهرست سیاه Redis نیست (${blacklisted:-خالی})"
fi

# =============================================================================
section "۳. کار ایمیل هشدار «ورود از دستگاه جدید» در صف Redis"
# =============================================================================
docker exec -i -e CHECK_EMAIL="$EMAIL" "$API" python - <<'PY' 2>&1 | collect
import os
from rq import Queue
from rq.registry import FailedJobRegistry, FinishedJobRegistry, ScheduledJobRegistry, StartedJobRegistry
from app.core.queue import QUEUE_NOTIFICATIONS, get_task_queue

queue = get_task_queue(QUEUE_NOTIFICATIONS)
ids = set(queue.job_ids)
for registry in (StartedJobRegistry, FinishedJobRegistry, FailedJobRegistry, ScheduledJobRegistry):
    ids |= set(registry(queue=queue).get_job_ids())
jobs = [job for job in queue.job_class.fetch_many(list(ids), connection=queue.connection) if job]
alerts = [job for job in jobs if job.func_name.endswith("_signin_email_task") and job.args and job.args[0] == os.environ["CHECK_EMAIL"]]
for job in alerts:
    details = job.args[1]
    print(f"{job.func_name.rsplit('.', 1)[1]} · وضعیت {job.get_status()} · {details['browser']} · {details['os']} · {details['ip']} · {details['location']}")
print(f"RESULT {'PASS' if len(alerts) == 1 else 'FAIL'} ورود دوم (Safari/iPhone) → {len(alerts)} کار ایمیل هشدار در صف «notifications» (ورود اول: هیچ)")
PY

# =============================================================================
section "۴. تشخیص ورود مشکوک با دیتابیس GeoIP واقعی سرور"
# =============================================================================
docker exec -i "$API" python - <<'PY' 2>&1 | collect
import time
from app.core import geoip
from app.core.config import settings
from app.core.sessions import detect_anomaly

tehran, frankfurt = geoip.lookup("5.160.0.1"), geoip.lookup("46.4.0.1")
if tehran is None or frankfurt is None:
    print(f"RESULT FAIL دیتابیس GeoIP در {settings.GEOIP_DB_PATH} آماده نیست (لاگ: geoip/update.log)")
    raise SystemExit
print(f"5.160.0.1 → {tehran.label} · 46.4.0.1 → {frankfurt.label}")
now = time.time()
history = [{"ts": now - 1800, "country_code": tehran.country_code, "lat": tehran.latitude, "lon": tehran.longitude}]
reasons = detect_anomaly(history, frankfurt, now)
for reason in reasons:
    print(f"دلیل: {reason}")
print(f"RESULT {'PASS' if len(reasons) == 2 else 'FAIL'} ورود از آلمان ۳۰ دقیقه بعد از تهران → Suspicious Login")
print(f"RESULT {'PASS' if not detect_anomaly(history, tehran, now) else 'FAIL'} ورود دوباره از تهران → عادی")
PY

cleanup

printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED" | tee -a "$REPORT"
info "گزارش کامل: ${PROJECT_DIR}/${REPORT}"
if ((FAILED == 0)); then
    printf '\033[1;32m[SESSIONS PASS] نشست باطل‌شده فوراً رد می‌شود، فهرست نشست‌ها جزئیات دستگاه را دارد و هشدار ورود در صف است\033[0m\n' | tee -a "$REPORT"
    exit 0
fi
printf '\033[1;31m[SESSIONS FAIL]\033[0m\n' | tee -a "$REPORT"
exit 1
