#!/usr/bin/env bash
# =============================================================================
# بازبینی نهایی محیط Staging پیش از انتشار — به دنبال «خطاهای پنهان»: چیزهایی که سایت را از کار
# نمی‌اندازند ولی در Production به کاربر آسیب می‌زنند (کار پس‌زمینه‌ی ناموفق، ری‌استارت پنهان
# کانتینر، خطای 5xx پراکنده، هشدار فعال، کندی).
#
#   bash deploy/staging_check.sh            (از ریشه‌ی پروژه، روی ماشین Staging)
#
# منابع: وضعیت کانتینرها (Docker)، Prometheus (همان داده‌های داشبوردهای Grafana) و لاگ سرویس‌ها.
# متغیرها: PROMETHEUS_URL (پیش‌فرض http://127.0.0.1:9090)، WINDOW (بازه‌ی بررسی، پیش‌فرض 24h)
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
WINDOW="${WINDOW:-24h}"
APP_SERVICES=(backend_api worker scheduler frontend postgres_db redis_cache backup)

failures=0
pass() { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
fail() { printf '  \033[1;31m✘ %s\033[0m\n' "$*"; failures=$((failures + 1)); }
step() { printf '\n\033[1;36m━━ %s\033[0m\n' "$*"; }

# promql <query> → اولین مقدار عددی نتیجه (یا 0)
promql() {
    curl -s --max-time 10 -G "${PROMETHEUS_URL}/api/v1/query" --data-urlencode "query=$1" \
        | grep -o '"value":\[[^,]*,"[^"]*"' | head -n 1 | sed 's/.*,"\([^"]*\)"/\1/' | grep . || echo 0
}
num() { awk "BEGIN { printf \"%.${2:-0}f\", $1 }"; }

printf '\033[1m🔎 بازبینی Staging — بازه‌ی %s تا %s\033[0m\n' "${WINDOW}" "$(date '+%Y-%m-%d %H:%M')"

step "۱. کانتینرها: همه بالا، سالم و بدون ری‌استارت پنهان"
for service in "${APP_SERVICES[@]}" prometheus grafana alertmanager; do
    ids="$(docker compose ps -q "${service}" 2>/dev/null)"
    if [[ -z "${ids}" ]]; then
        fail "${service}: کانتینری در حال اجرا نیست"
        continue
    fi
    for id in ${ids}; do
        read -r state health restarts name < <(docker inspect --format \
            '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}} {{.RestartCount}} {{.Name}}' "${id}")
        if [[ "${state}" == running && "${health}" != unhealthy && "${restarts}" == 0 ]]; then
            pass "${name#/}: ${state}${health:+ (${health})}، ری‌استارت: ${restarts}"
        else
            fail "${name#/}: وضعیت=${state} سلامت=${health} ری‌استارت=${restarts}"
        fi
    done
done

step "۲. مانیتورینگ (Prometheus — داده‌های داشبوردهای Grafana)"
down="$(promql 'count(up == 0)')"
total_targets="$(promql 'count(up)')"
[[ "${down}" == 0 ]] && pass "همه‌ی ${total_targets} منبع متریک در دسترس‌اند" || fail "${down} منبع متریک قطع است"
firing="$(promql 'count(ALERTS{alertstate="firing"})')"
[[ "${firing}" == 0 ]] && pass "هیچ هشدار فعالی (Firing) وجود ندارد" || fail "${firing} هشدار فعال — http://localhost:9093"
requests="$(promql "sum(increase(http_requests_total[${WINDOW}]))")"
errors="$(promql "sum(increase(http_requests_total{status=~\"5..\"}[${WINDOW}]))")"
[[ "$(num "${errors}")" == 0 ]] && pass "خطای سرور (5xx): ۰ از $(num "${requests}") درخواست" \
    || fail "$(num "${errors}") خطای 5xx از $(num "${requests}") درخواست"
p95="$(promql 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[1h])))')"
[[ "${p95}" == NaN ]] && p95=0
awk "BEGIN { exit !(${p95} < 1) }" && pass "زمان پاسخ صدک ۹۵ (ساعت اخیر): $(num "${p95} * 1000") میلی‌ثانیه" \
    || fail "زمان پاسخ صدک ۹۵ بالاست: ${p95} ثانیه"
failed_jobs="$(promql 'max(ats_rq_jobs{state="failed"})')"
[[ "$(num "${failed_jobs}")" == 0 ]] && pass "کار ناموفق در صف پس‌زمینه: ۰" || fail "$(num "${failed_jobs}") کار ناموفق در صف پس‌زمینه (FailedJobRegistry)"

step "۳. لاگ سرویس‌ها (${WINDOW} اخیر): Exception / ERROR / FATAL"
log_errors="$(docker compose logs --since "${WINDOW}" --no-color "${APP_SERVICES[@]}" 2>/dev/null \
    | grep -E 'Traceback|ERROR|CRITICAL|FATAL|PANIC' || true)"
if [[ -z "${log_errors}" ]]; then
    pass "هیچ خطایی در لاگ‌ها نیست"
else
    fail "$(grep -c . <<< "${log_errors}") خط خطا در لاگ‌ها — پرتکرارترین‌ها:"
    sed -E 's/^[^|]*\| //; s/[0-9]{4}-[0-9-]+[ T][0-9:.,]+//; s/[0-9a-f]{8}-[0-9a-f-]{27}/<id>/g' <<< "${log_errors}" \
        | sort | uniq -c | sort -rn | head -n 8 | cut -c1-170 | sed 's/^/      /'
fi

echo
if (( failures == 0 )); then
    printf '\033[1;32m[STAGING CHECK PASS] هیچ خطای پنهانی پیدا نشد — آماده‌ی انتشار\033[0m\n'
else
    printf '\033[1;31m[STAGING CHECK FAIL] %d مورد نیازمند بررسی\033[0m\n' "${failures}"
    exit 1
fi
