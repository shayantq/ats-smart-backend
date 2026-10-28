#!/usr/bin/env bash
# =============================================================================
# راستی‌آزمایی Zero-Trust روی سرور Production (Docker Compose) — فقط خواندن و آزمون، بدون تغییر داده:
#
#   cd /opt/ats-smart && bash deploy/zero-trust-check.sh
#
#   ۰. توپولوژی شبکه: هر سرویس فقط عضو شبکه‌های لازم
#   ۱. توکن سرویس‌به‌سرویس از داخل کانتینر Worker: بدون هدر / منقضی / audience اشتباه / کلید ناشناخته ← 401،
#      توکن معتبر ← 200؛ همان مسیر از اینترنت (دامنه‌ی عمومی) ← 404
#   ۲. لایه‌ی شبکه: کانتینر غیرمجاز (روی شبکه‌ی وب، کنار فرانت‌اند) اتصال TCP به PostgreSQL/Redis را برقرار
#      نمی‌کند (Timeout، نه خطای برنامه)؛ API همان اتصال را دارد
# =============================================================================
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

RUN_ID="$(date +%Y%m%d%H%M%S)"
REPORT_DIR="${REPORT_DIR:-reports}"
REPORT="${REPORT_DIR}/zero-trust-${RUN_ID}.log"
mkdir -p "${REPORT_DIR}"
PASSED=0
FAILED=0

section() { printf '\n\033[1m━━━ %s ━━━\033[0m\n' "$*" | tee -a "$REPORT"; }
pass() { PASSED=$((PASSED + 1)); printf '  \033[32m✔ PASS\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
fail() { FAILED=$((FAILED + 1)); printf '  \033[31m✘ FAIL\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
info() { printf '          %s\n' "$*" | tee -a "$REPORT"; }

PROJECT="$(bash deploy/compose.sh config 2>/dev/null | sed -n 's/^name: //p' | head -n 1)"
PROJECT="${PROJECT:-ats-smart}"
container() {
    docker ps -q --filter "label=com.docker.compose.project=${PROJECT}" \
        --filter "label=com.docker.compose.service=$1" | head -n 1
}
networks_of() {
    docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$1" 2>/dev/null
}
ip_on() {  # <container> <network-substring>
    docker inspect --format '{{range $name, $net := .NetworkSettings.Networks}}{{$name}}={{$net.IPAddress}} {{end}}' "$1" \
        | tr ' ' '\n' | grep -- "$2" | head -n 1 | cut -d= -f2
}

printf '\033[1mATS Smart — راستی‌آزمایی Zero-Trust (سرور Production)\033[0m\n' | tee "$REPORT"
printf 'host: %s · %s · project: %s\n' "$(hostname)" "$(date '+%Y-%m-%d %H:%M:%S')" "$PROJECT" | tee -a "$REPORT"

WORKER="$(container worker)"
API="$(container backend_api)"
POSTGRES="$(container postgres_db)"
REDIS="$(container redis_cache)"
FRONTEND="$(container frontend)"
[[ -n "$WORKER" && -n "$API" && -n "$POSTGRES" && -n "$REDIS" ]] || { echo "کانتینرهای پروژه بالا نیستند" >&2; exit 2; }

# =============================================================================
section "۰. تفکیک شبکه — هر سرویس فقط عضو شبکه‌های لازم"
# =============================================================================
for service in postgres_db redis_cache backend_api worker frontend gateway; do
    id="$(container "$service")"
    [[ -n "$id" ]] && info "$(printf '%-12s %s' "$service" "$(networks_of "$id")")"
done
pg_networks="$(networks_of "$POSTGRES")"
[[ "$pg_networks" == *ats_data* && "$pg_networks" != *ats_network* ]] \
    && pass "PostgreSQL فقط در شبکه‌ی داخلی ats_data است (بدون اینترنت، بیرون از لایه‌ی وب)" \
    || fail "شبکه‌های PostgreSQL: ${pg_networks}"
[[ -n "$FRONTEND" && "$(networks_of "$FRONTEND")" != *ats_data* ]] \
    && pass "فرانت‌اند عضو شبکه‌ی داده نیست" || fail "فرانت‌اند به شبکه‌ی داده دسترسی دارد"

# =============================================================================
section "۱. توکن سرویس‌به‌سرویس (X-Internal-Auth) — از داخل کانتینر Worker به API"
# =============================================================================
docker exec -i "$WORKER" python - <<'PY' 2>&1 | tee -a "$REPORT"
import time, uuid
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwt
from app.core.service_auth import SERVICE_AUTH_HEADER, _private_key, issue_service_token

URL = "http://backend_api:8000/api/v1/internal/whoami"
now = int(time.time())


def signed(key, **overrides):
    claims = {"iss": "worker", "sub": "worker", "aud": "backend-api", "iat": now, "nbf": now,
              "exp": now + 60, "jti": uuid.uuid4().hex, "typ": "service", **overrides}
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "worker"})


rogue = ec.generate_private_key(ec.SECP256R1()).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
cases = [
    ("بدون هدر X-Internal-Auth", {}, 401),
    ("توکن منقضی", {SERVICE_AUTH_HEADER: signed(_private_key(), iat=now - 600, nbf=now - 600, exp=now - 300)}, 401),
    ("audience اشتباه (grafana)", {SERVICE_AUTH_HEADER: signed(_private_key(), aud="grafana")}, 401),
    ("امضا با کلید ناشناخته (جعل هویت worker)", {SERVICE_AUTH_HEADER: signed(rogue)}, 401),
    ("توکن معتبر Worker (ES256، ۶۰ ثانیه)", {SERVICE_AUTH_HEADER: issue_service_token(audience="backend-api")}, 200),
]
with httpx.Client(timeout=10) as client:
    for title, headers, expected in cases:
        code = client.get(URL, headers=headers).status_code
        print(f"RESULT {'PASS' if code == expected else 'FAIL'} {title} → {code} (انتظار {expected})")
PY
while IFS= read -r line; do
    result="${line#RESULT }"
    [[ "$result" == PASS* ]] && pass "${result#PASS }" || fail "${result#FAIL }"
done < <(grep "^RESULT " "$REPORT" | tail -n 5)

public_base="$(grep -E '^PUBLIC_BASE_URL=' .env 2>/dev/null | cut -d= -f2-)"
if [[ -n "$public_base" ]]; then
    token="$(docker exec "$WORKER" python -c "from app.core.service_auth import issue_service_token; print(issue_service_token(audience='backend-api'))" 2>/dev/null)"
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H "X-Internal-Auth: ${token}" "${public_base}/api/v1/internal/whoami")"
    [[ "$code" == "404" ]] && pass "همان مسیر از اینترنت (${public_base}) حتی با توکن معتبر: ${code} — مسیرهای داخلی بیرون وجود ندارند" \
        || fail "مسیر داخلی از اینترنت: ${code}"
fi

# =============================================================================
section "۲. لایه‌ی شبکه (TCP/IP) — کانتینر غیرمجاز ← PostgreSQL / Redis"
# =============================================================================
web_network="$(networks_of "${FRONTEND:-$API}" | tr ' ' '\n' | grep -m1 ats_network)"
pg_ip="$(ip_on "$POSTGRES" ats_data)"
redis_ip="$(ip_on "$REDIS" ats_cache)"
info "مهاجم فرضی: کانتینر ناشناس روی شبکه‌ی وب (${web_network}) — کنار فرانت‌اند/Gateway"
info "PostgreSQL ← ${pg_ip}:5432 · Redis ← ${redis_ip}:6379"

probe() {  # <ip> <port> → «ثانیه|نتیجه»
    docker run --rm --network "$web_network" busybox:1.36 sh -c \
        "s=\$(date +%s); if nc -w 5 $1 $2 </dev/null >/dev/null 2>&1; then r=CONNECTED; else r=DROPPED; fi; echo \"\$((\$(date +%s)-s))|\$r\"" 2>/dev/null
}
for target in "PostgreSQL|${pg_ip}|5432" "Redis|${redis_ip}|6379"; do
    IFS='|' read -r name ip port <<<"$target"
    IFS='|' read -r seconds outcome <<<"$(probe "$ip" "$port")"
    if [[ "$outcome" == DROPPED && "${seconds:-0}" -ge 4 ]]; then
        pass "اتصال TCP کانتینر غیرمجاز به ${name} (${ip}:${port}) بعد از ${seconds} ثانیه بی‌پاسخ ماند (بسته‌ها در لایه‌ی شبکه دور ریخته شدند)"
    else
        fail "${name} از کانتینر غیرمجاز: ${outcome:-?} در ${seconds:-?} ثانیه"
    fi
done
not_found="$(docker run --rm --network "$web_network" busybox:1.36 nslookup postgres_db 2>&1 | grep -ciE "can't find|NXDOMAIN" || true)"
[[ "$not_found" -ge 1 ]] && pass "نام postgres_db برای کانتینر غیرمجاز حتی Resolve نمی‌شود" || fail "postgres_db از شبکه‌ی وب Resolve شد"

allowed="$(docker exec "$API" python -c "import socket; socket.create_connection(('postgres_db', 5432), 3).close(); socket.create_connection(('redis_cache', 6379), 3).close(); print('ok')" 2>&1)"
[[ "$allowed" == ok ]] && pass "API (عضو ats_data و ats_cache) به PostgreSQL و Redis وصل می‌شود" || fail "اتصال مجاز API: ${allowed}"

printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED" | tee -a "$REPORT"
info "گزارش کامل: ${PROJECT_DIR}/${REPORT}"
if ((FAILED == 0)); then
    printf '\033[1;32m[ZERO TRUST PASS] سرویس بدون توکن معتبر رد می‌شود و پایگاه داده از کانتینر غیرمجاز در لایه‌ی شبکه در دسترس نیست\033[0m\n' | tee -a "$REPORT"
    exit 0
fi
printf '\033[1;31m[ZERO TRUST FAIL]\033[0m\n' | tee -a "$REPORT"
exit 1
