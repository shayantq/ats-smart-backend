#!/usr/bin/env bash
# =============================================================================
# تست بار/استرس و بررسی خودکار معیارهای پذیرش HPA و Ingress
#
#   bash k8s/hpa-stress.sh                       تست کامل (پیش‌فرض: ۱۵۰ کاربر، ۱ دقیقه افزایش، ۳ دقیقه اوج)
#   LOAD_USERS=250 LOAD_HOLD=300 bash k8s/hpa-stress.sh
#   KEEP_DATA=1 ...                              آگهی‌های آزمایشی پس از تست پاک نشوند
#
#   ۱. Scale Up:   با عبور CPU/RAM بک‌اند از ۷۵٪، HPA خودکار Pod اضافه می‌کند
#   ۲. Scale Down: پس از قطع ترافیک، Pod های اضافه خودکار تا حداقل کم می‌شوند
#   ۳. Ingress:    ترافیک بین همه‌ی Pod های فعال پخش می‌شود و هیچ پاسخ 502/5xx به کاربر نمی‌رسد
#
# بار با یک Job داخل کلاستر (Locust، k8s/loadtest/) و از مسیر واقعی کاربر — Service ورودی NGINX Ingress —
# تولید می‌شود. جدول زمانی کامل در k8s/loadtest/reports/ ذخیره می‌شود.
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

# اجرا از PowerShell: دستور «bash» ویندوز، bash توزیع WSL است — آنجا نسخه‌ی ویندوزی kubectl استفاده می‌شود
if grep -qi microsoft /proc/version 2>/dev/null && command -v kubectl.exe >/dev/null 2>&1; then
    kubectl() { kubectl.exe "$@"; }
fi
command -v kubectl >/dev/null 2>&1 || { echo "kubectl پیدا نشد" >&2; exit 2; }

cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-ats-smart}"
INGRESS_NAMESPACE="${INGRESS_NAMESPACE:-nginx-ingress}"
LOAD_USERS="${LOAD_USERS:-150}"
LOAD_RAMP="${LOAD_RAMP:-60}"
LOAD_HOLD="${LOAD_HOLD:-180}"
SCALE_DOWN_TIMEOUT="${SCALE_DOWN_TIMEOUT:-900}"
INTERVAL=15
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT_DIR="k8s/loadtest/reports"
REPORT="${REPORT_DIR}/hpa-stress-${STAMP}.log"
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

prom_query() {  # <PromQL> → خطوط «برچسب‌ها مقدار»
    k exec deploy/prometheus -c prometheus -- wget -qO- "http://127.0.0.1:9090/api/v1/query?query=$("$PYTHON" -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1")" 2>/dev/null \
        | "$PYTHON" -c '
import json, sys
for r in json.load(sys.stdin)["data"]["result"]:
    labels = " ".join(f"{k}={v}" for k, v in sorted(r["metric"].items()))
    print(labels or "-", round(float(r["value"][1])))'
}

hpa_line() {  # <name> → «فعلی/مطلوب cpu% mem%»
    k get hpa "$1" -o jsonpath='{.status.currentReplicas}/{.status.desiredReplicas} {range .status.currentMetrics[*]}{.resource.name}={.resource.current.averageUtilization}% {end}' 2>/dev/null
}

replicas_of() { k get deploy "$1" -o jsonpath='{.status.readyReplicas}' 2>/dev/null; }

printf '\033[1mATS Smart — تست بار و مقیاس‌دهی خودکار (HPA + NGINX Ingress)\033[0m\n' | tee "$REPORT"
printf 'context: %s · %s · %s کاربر هم‌زمان، %s ثانیه افزایش، %s ثانیه اوج\n' \
    "$(kubectl config current-context)" "$(date '+%Y-%m-%d %H:%M:%S')" "$LOAD_USERS" "$LOAD_RAMP" "$LOAD_HOLD" | tee -a "$REPORT"

# =============================================================================
section "پیش‌نیازها"
# =============================================================================
if kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/"$NAMESPACE"/pods >/dev/null 2>&1; then
    pass "metrics-server: متریک زنده‌ی CPU/RAM Pod ها در دسترس است"
else
    fail "metrics-server در دسترس نیست (kubectl apply -k k8s/addons/metrics-server)"; exit 1
fi
ingress_port="$(kubectl -n "$INGRESS_NAMESPACE" get svc nginx-ingress -o jsonpath='{.spec.ports[?(@.name=="http")].port}' 2>/dev/null)"
ingress_host="$(k get ingress ats-smart -o jsonpath='{.spec.rules[0].host}' 2>/dev/null)"
ingress_ready="$(kubectl -n "$INGRESS_NAMESPACE" get deploy nginx-ingress -o jsonpath='{.status.readyReplicas}' 2>/dev/null)"
if [[ -n "$ingress_port" && -n "$ingress_host" && -n "$ingress_ready" ]]; then
    pass "NGINX Ingress Controller: ${ingress_ready} Pod آماده · دامنه ${ingress_host} · پورت ${ingress_port}"
else
    fail "Ingress Controller یا Ingress برنامه پیدا نشد (bash k8s/deploy.sh)"; exit 1
fi
k get hpa | sed 's/^/  /' | tee -a "$REPORT"
min_replicas="$(k get hpa backend-api -o jsonpath='{.spec.minReplicas}')"
max_replicas="$(k get hpa backend-api -o jsonpath='{.spec.maxReplicas}')"
start_replicas="$(replicas_of backend-api)"
info "بک‌اند پیش از تست: ${start_replicas} Pod (حداقل ${min_replicas}، حداکثر ${max_replicas}) · $(hpa_line backend-api)"

# =============================================================================
section "آماده‌سازی داده: آگهی‌های شغلی آزمایشی (از طریق خودِ API)"
# =============================================================================
seed="$(k exec -i deploy/backend-api -c backend-api -- python - <<'PY' 2>&1
import json, secrets, urllib.request

BASE = "http://127.0.0.1:8000/api/v1"

def call(method, path, body=None, token=None):
    request = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read() or b"null")

email, password = f"loadtest-hr-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(16)
call("POST", "/auth/register", {"email": email, "password": password, "role": "HR_Manager"})
token = call("POST", "/auth/login", {"email": email, "password": password})["access_token"]
departments = ["فنی", "مالی", "فروش", "منابع انسانی", "پشتیبانی"]
for index in range(40):
    call("POST", "/jobs/", {
        "title": f"[LoadTest] موقعیت شغلی شماره {index + 1}",
        "department": departments[index % len(departments)],
        "description": "آگهی آزمایشی تست بار — " + "شرح وظایف و مهارت‌های مورد نیاز. " * 20,
        "skills_required": ["Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes"][: 1 + index % 5],
        "salary_range": "توافقی",
        "required_seniority": ["Junior", "Mid-Level", "Senior"][index % 3],
        "location": "تهران",
    }, token)
print("SEEDED", email)
PY
)"
if grep -q "^SEEDED" <<<"$seed"; then
    pass "۴۰ آگهی آزمایشی ساخته شد (کاربر HR موقت: $(grep '^SEEDED' <<<"$seed" | cut -d' ' -f2))"
else
    fail "ساخت داده‌ی آزمایشی: ${seed}"; exit 1
fi

# =============================================================================
section "اجرای بار (Locust داخل کلاستر ← NGINX Ingress ← Pod ها)"
# =============================================================================
target="http://nginx-ingress.${INGRESS_NAMESPACE}.svc.cluster.local:${ingress_port}"
k delete job loadtest --ignore-not-found --wait=true >/dev/null 2>&1
k create configmap loadtest-locustfile --from-file=locustfile.py=k8s/loadtest/locustfile.py --dry-run=client -o yaml | k apply -f - >/dev/null
sed -e "s|__TARGET_URL__|${target}|" -e "s|__USERS__|${LOAD_USERS}|" -e "s|__RAMP__|${LOAD_RAMP}|" \
    -e "s|__HOLD__|${LOAD_HOLD}|" -e "s|__HOST_HEADER__|${ingress_host}|" k8s/loadtest/locust-job.yaml | k apply -f - >/dev/null
info "مقصد: ${target} (Host: ${ingress_host})"
load_started=$SECONDS

printf '\n  %-8s %-8s %-12s %-24s %-14s %-10s %-8s\n' TIME PHASE BACKEND "BACKEND CPU/MEM" WORKER FRONTEND INGRESS | tee -a "$REPORT"
peak=0
first_scale_up=""
phase="LOAD"
scale_down_started=""
while true; do
    elapsed=$((SECONDS - load_started))
    line="$(hpa_line backend-api)"
    current="${line%%/*}"
    metrics="${line#* }"
    [[ "$current" =~ ^[0-9]+$ ]] || current=0
    ((current > peak)) && peak=$current
    if [[ -z "$first_scale_up" && "$current" -gt "$min_replicas" ]]; then first_scale_up=$elapsed; fi
    printf '  %-8s %-8s %-12s %-24s %-14s %-10s %-8s\n' "$(printf '%02d:%02d' $((elapsed / 60)) $((elapsed % 60)))" "$phase" \
        "${line%% *}" "$metrics" "$(hpa_line worker | cut -d' ' -f1)" "$(hpa_line frontend | cut -d' ' -f1)" \
        "$(kubectl -n "$INGRESS_NAMESPACE" get hpa nginx-ingress -o jsonpath='{.status.currentReplicas}' 2>/dev/null)" | tee -a "$REPORT"

    if [[ "$phase" == "LOAD" ]]; then
        state="$(k get job loadtest -o jsonpath='{.status.succeeded}{.status.failed}' 2>/dev/null)"
        if [[ -n "$state" ]]; then
            phase="COOLDOWN"
            scale_down_started=$SECONDS
            load_duration=$elapsed
        fi
    elif [[ "$current" -le "$min_replicas" ]]; then
        scale_down_duration=$((SECONDS - scale_down_started))
        break
    elif ((SECONDS - scale_down_started > SCALE_DOWN_TIMEOUT)); then
        scale_down_duration=""
        break
    fi
    sleep "$INTERVAL"
done

# =============================================================================
section "نتیجه‌ی Locust (دید کاربر)"
# =============================================================================
locust_log="$(k logs job/loadtest 2>/dev/null)"
grep -E "^\s*(Type|---|GET|POST|\s+Aggregated)|Aggregated|Percentage|^\s*[0-9]+%|STATUS_CODES|TOTAL_REQUESTS|BAD_GATEWAY|NO-5XX" <<<"$locust_log" \
    | grep -vE "^\[" | sed 's/^/  /' | tee -a "$REPORT"
total_requests="$(grep -oE "^TOTAL_REQUESTS [0-9]+" <<<"$locust_log" | cut -d' ' -f2)"
bad_gateway="$(grep -oE "^BAD_GATEWAY_502 [0-9]+" <<<"$locust_log" | cut -d' ' -f2)"
stale_retries="$(grep -oE "^STALE_CONNECTION_RETRIES [0-9]+" <<<"$locust_log" | cut -d' ' -f2)"

# =============================================================================
section "معیار ۱: Scale Up خودکار با عبور مصرف از ۷۵٪"
# =============================================================================
k describe hpa backend-api | sed -n '/^Events:/,$p' | grep -E "SuccessfulRescale" | sed 's/^/  /' | tee -a "$REPORT"
if [[ -n "$first_scale_up" && "$peak" -gt "$min_replicas" ]]; then
    pass "بک‌اند از ${min_replicas} به ${peak} Pod رسید؛ اولین Scale Up ${first_scale_up} ثانیه پس از شروع بار"
else
    fail "HPA بک‌اند Pod اضافه نکرد (اوج: ${peak}) — LOAD_USERS را بیشتر کنید"
fi

# =============================================================================
section "معیار ۲: Scale Down خودکار پس از کاهش ترافیک"
# =============================================================================
if [[ -n "${scale_down_duration:-}" ]]; then
    pass "پس از پایان بار، بک‌اند از ${peak} به $(replicas_of backend-api) Pod (حداقل) برگشت — در ${scale_down_duration} ثانیه (شامل ۲ دقیقه آرامش HPA)"
else
    fail "بک‌اند در ${SCALE_DOWN_TIMEOUT} ثانیه به حداقل برنگشت: $(hpa_line backend-api)"
fi

# =============================================================================
section "معیار ۳: توزیع بار Ingress بین همه‌ی Pod های فعال، بدون 502"
# =============================================================================
window="$(((SECONDS - load_started) / 60 + 2))m"
info "پاسخ‌های Pod های بک‌اند از دید NGINX Ingress (هر سطر یک Pod، بازه‌ی ${window} اخیر):"
distribution="$(prom_query "sum by (server, code) (increase(nginx_ingress_controller_upstream_server_response_latency_ms_count{service=\"backend-api\"}[${window}]))")"
sed 's/^/            /' <<<"$distribution" | tee -a "$REPORT"
served_pods="$(awk '$NF > 0 {for (i = 1; i <= NF; i++) if ($i ~ /^server=/) print $i}' <<<"$distribution" | sort -u | wc -l | tr -d ' ')"
upstream_5xx="$(awk '{for (i = 1; i <= NF; i++) if ($i ~ /^code=5/) s += $NF} END {printf "%d", s}' <<<"$distribution")"
if [[ "$served_pods" -ge "$peak" && "$peak" -gt 1 ]]; then
    pass "Ingress به هر ${served_pods} Pod بک‌اند (همه‌ی نسخه‌های ساخته‌شده توسط HPA) درخواست فرستاد"
else
    fail "فقط ${served_pods} Pod از ${peak} Pod اوج درخواست گرفتند"
fi
if [[ -n "$total_requests" && "${bad_gateway:-1}" == "0" && "$(grep -c '\[NO-5XX PASS\]' <<<"$locust_log")" == "1" ]]; then
    pass "${total_requests} درخواست کاربر از Ingress — ۰ پاسخ 502 و ۰ خطای سرور (حتی حین افزوده/حذف شدن Pod ها)"
    info "اتصال keep-alive بسته‌شده هنگام Reload پیکربندی NGINX: ${stale_retries:-0} مورد — هر کدام مثل مرورگر یک بار خودکار تکرار و موفق شد"
else
    fail "خطا از دید کاربر: 502=${bad_gateway:-?} ($(grep -E '^\[NO-5XX' <<<"$locust_log"))"
fi
((upstream_5xx == 0)) && pass "هیچ Pod بک‌اندی به Ingress پاسخ 5xx نداد" || fail "${upstream_5xx} پاسخ 5xx از Pod ها (Ingress آن‌ها را روی Pod دیگر تکرار کرد)"

# =============================================================================
section "پاک‌سازی"
# =============================================================================
if [[ "${KEEP_DATA:-0}" != "1" ]]; then
    printf '%s\n' "delete from jobs where title like '[LoadTest]%';" "delete from users where email like 'loadtest-hr-%@example.com';" \
        | k exec -i postgres-0 -c postgres -- sh -c 'psql -X -q -U "$POSTGRES_USER" -d smart_ats_db' >/dev/null 2>&1 \
        && info "آگهی‌ها و کاربر آزمایشی حذف شدند" || info "پاک‌سازی داده‌ی آزمایشی انجام نشد (KEEP_DATA=1 برای نگه‌داشتن)"
fi
info "گزارش کامل: ${REPORT}"

printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED" | tee -a "$REPORT"
if ((FAILED == 0)); then
    printf '\033[1;32m[HPA & INGRESS PASS] همه‌ی معیارهای پذیرش برقرارند\033[0m\n' | tee -a "$REPORT"
    exit 0
fi
printf '\033[1;31m[HPA & INGRESS FAIL]\033[0m\n' | tee -a "$REPORT"
exit 1
