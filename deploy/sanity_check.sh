#!/usr/bin/env bash
# =============================================================================
# تست سلامت (Sanity Check) محصول روی دامنه‌ی اصلی — بلافاصله بعد از هر استقرار (CI/CD) یا دستی.
# همه‌ی درخواست‌ها از بیرون و از مسیر کاربر واقعی (دامنه → gateway → ...) فرستاده می‌شوند.
#
#   bash deploy/sanity_check.sh <آدرس سایت> [نسخه‌ی مورد انتظار]
#   bash deploy/sanity_check.sh http://smart-ats.localhost sha-1a2b3c4
#
# PROMETHEUS_URL (اختیاری، مثلاً http://127.0.0.1:9090 روی خود سرور): بررسی توزیع بار بین نسخه‌های بک‌اند
# خروج با کد ۱ اگر حتی یک بررسی شکست بخورد.
# =============================================================================
set -uo pipefail

BASE_URL="${1:?آدرس سایت را بدهید، مثلاً http://smart-ats.localhost}"
BASE_URL="${BASE_URL%/}"
EXPECTED_VERSION="${2:-}"
PROMETHEUS_URL="${PROMETHEUS_URL:-}"
LB_REQUESTS="${LB_REQUESTS:-90}"

failures=0
pass() { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
fail() { printf '  \033[1;31m✘ %s\033[0m\n' "$*"; failures=$((failures + 1)); }
step() { printf '\n\033[1;36m━━ %s\033[0m\n' "$*"; }

# fetch <path> → متغیرهای code, body, headers, time
fetch() {
    local tmp_headers tmp_body
    tmp_headers="$(mktemp)"; tmp_body="$(mktemp)"
    read -r code time < <(curl -s --max-time 15 -D "${tmp_headers}" -o "${tmp_body}" \
        -w '%{http_code} %{time_total}' "${BASE_URL}$1" || echo "000 0")
    headers="$(tr -d '\r' < "${tmp_headers}")"
    body="$(cat "${tmp_body}")"
    rm -f "${tmp_headers}" "${tmp_body}"
}

json_field() { sed -n "s/.*\"$1\":\"\\([^\"]*\\)\".*/\\1/p" <<< "$2"; }

printf '\033[1m🔎 Sanity Check: %s  (%s)\033[0m\n' "${BASE_URL}" "$(date '+%Y-%m-%d %H:%M:%S')"

step "۱. دامنه و Gateway"
fetch /gateway-health
[[ "${code}" == 200 && "${body}" == ok* ]] && pass "Gateway در دسترس است (${time}s)" || fail "Gateway پاسخ درستی نداد (HTTP ${code})"

step "۲. صفحه‌ی اصلی سایت (فرانت‌اند)"
fetch /
if [[ "${code}" == 200 && "${body}" == *'id="root"'* ]]; then
    pass "صفحه‌ی اصلی بارگذاری شد — HTTP 200 در ${time}s"
else
    fail "صفحه‌ی اصلی سالم نیست (HTTP ${code})"
fi
for header in Content-Security-Policy X-Frame-Options X-Content-Type-Options Referrer-Policy; do
    grep -qi "^${header}:" <<< "${headers}" && pass "هدر امنیتی ${header}" || fail "هدر امنیتی ${header} وجود ندارد"
done
asset="$(grep -o '/assets/[^"]*\.js' <<< "${body}" | head -n 1)"
if [[ -n "${asset}" ]]; then
    fetch "${asset}"
    [[ "${code}" == 200 ]] && pass "فایل‌های JavaScript برنامه (${asset})" || fail "فایل ${asset} بارگذاری نشد (HTTP ${code})"
fi

step "۳. API و نسخه‌ی مستقرشده"
fetch /api/v1/health
version="$(json_field version "${body}")"
[[ "${code}" == 200 ]] && pass "API سالم است — نسخه‌ی در حال اجرا: ${version}" || fail "API سالم نیست (HTTP ${code})"
if [[ -n "${EXPECTED_VERSION}" ]]; then
    [[ "${version}" == "${EXPECTED_VERSION}" ]] && pass "نسخه‌ی جدید (${EXPECTED_VERSION}) روی دامنه فعال است" \
        || fail "نسخه‌ی روی دامنه (${version}) با نسخه‌ی مورد انتظار (${EXPECTED_VERSION}) یکی نیست"
fi

step "۴. آمادگی کامل: دیتابیس و Redis"
fetch /api/v1/health/ready
if [[ "${code}" == 200 ]]; then
    pass "PostgreSQL: $(json_field database "${body}") · Redis: $(json_field redis "${body}")"
else
    fail "سرویس آماده نیست (HTTP ${code}): ${body}"
fi

step "۵. مسیرهای کاربردی"
fetch "/api/v1/jobs/?limit=5"
[[ "${code}" == 200 ]] && pass "فهرست آگهی‌های شغلی (کوئری واقعی دیتابیس) — ${time}s" || fail "فهرست آگهی‌ها (HTTP ${code})"
fetch /api/v1/auth/me
[[ "${code}" == 401 ]] && pass "مسیرهای محافظت‌شده بدون توکن رد می‌شوند (401)" || fail "/auth/me بدون توکن: HTTP ${code} (انتظار 401)"
fetch /metrics
[[ "${body}" != *"# HELP"* ]] && pass "متریک‌های داخلی از بیرون در دسترس نیستند (HTTP ${code})" || fail "/metrics از بیرون باز است"
fetch /grafana/api/health
[[ "${code}" == 200 && "${body}" == *'"database"'* ]] && pass "داشبورد مانیتورینگ Grafana (/grafana/) — $(json_field database "${body}")"     || fail "Grafana از مسیر /grafana/ پاسخ درستی نداد (HTTP ${code})"

if [[ -n "${PROMETHEUS_URL}" ]]; then
    step "۶. توزیع بار (Load Balancing) بین نسخه‌های بک‌اند"
    for _ in $(seq 1 "${LB_REQUESTS}"); do
        curl -s -o /dev/null --max-time 10 "${BASE_URL}/api/v1/health/ready" &
    done
    wait
    echo "  ${LB_REQUESTS} درخواست هم‌زمان فرستاده شد؛ انتظار برای Scrape بعدی Prometheus..."
    sleep 20
    query='sum by (instance) (increase(http_requests_total{route="/api/v1/health/ready"}[1m]))'
    result="$(curl -s --max-time 10 -G "${PROMETHEUS_URL}/api/v1/query" --data-urlencode "query=${query}")"
    distribution="$(grep -o '"instance":"[^"]*"},"value":\[[^,]*,"[^"]*"' <<< "${result}" \
        | sed 's/"instance":"\([^"]*\)"},"value":\[[^,]*,"\([^"]*\)"/\1 \2/')"
    active=0
    while read -r instance value; do
        [[ -z "${instance}" ]] && continue
        printf '    نسخه‌ی بک‌اند %-20s ≈ %.0f درخواست\n' "${instance}" "${value}"
        awk "BEGIN { exit !(${value} > 0) }" && active=$((active + 1))
    done <<< "${distribution}"
    (( active >= 2 )) && pass "بار بین ${active} نسخه‌ی بک‌اند پخش شد" \
        || fail "بار فقط به ${active} نسخه رسید (انتظار حداقل ۲)"
fi

echo
if (( failures == 0 )); then
    printf '\033[1;32m[SANITY PASS] همه‌ی بررسی‌ها روی %s موفق بود\033[0m\n' "${BASE_URL}"
else
    printf '\033[1;31m[SANITY FAIL] %d بررسی ناموفق روی %s\033[0m\n' "${failures}" "${BASE_URL}"
    exit 1
fi
