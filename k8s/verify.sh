#!/usr/bin/env bash
# =============================================================================
# بررسی خودکار معیارهای پذیرش مهاجرت به Kubernetes
#
#   bash k8s/verify.sh                  هر سه معیار (شامل حذف Pod پستگرس برای آزمون پایداری داده)
#   bash k8s/verify.sh --deep           + حذف کامل StatefulSet پستگرس و ساخت دوباره‌ی آن
#   bash k8s/verify.sh --no-disruption  فقط بررسی‌های بدون اختلال (معیار ۱ و ۲)
#
#   ۱. همه‌ی ۱۰ سرویس مستقر و همه‌ی Pod ها در وضعیت Running/Ready
#   ۲. ارتباط پایدار شبکه‌ی داخلی: DNS، بک‌اند ↔ PostgreSQL/Redis، Worker ↔ PostgreSQL/Redis،
#      فرانت‌اند ↔ بک‌اند (۲۰۰ درخواست پیاپی)، Target های Prometheus، نبود خطای اتصال در لاگ‌ها
#   ۳. ماندگاری داده‌ی PostgreSQL روی Persistent Volume پس از از کار افتادن/حذف Pod
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

# اجرا از PowerShell: دستور «bash» ویندوز، bash توزیع WSL است که kubectl/docker لینوکسی ندارد و
# localhost آن هم localhost ویندوز نیست — آنجا نسخه‌های ویندوزی (kubectl.exe و ...) استفاده می‌شوند
if grep -qi microsoft /proc/version 2>/dev/null; then
    for tool in kubectl docker curl; do
        if command -v "${tool}.exe" >/dev/null 2>&1; then eval "${tool}() { ${tool}.exe \"\$@\"; }"; fi
    done
fi
command -v kubectl >/dev/null 2>&1 || { echo "kubectl پیدا نشد — Docker Desktop (با Kubernetes فعال) نصب و در حال اجراست؟" >&2; exit 2; }

cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-ats-smart}"
OVERLAY="${OVERLAY:-local}"
DISRUPT=1
DEEP=0
for arg in "$@"; do
    case "$arg" in
        --no-disruption) DISRUPT=0 ;;
        --deep) DEEP=1 ;;
        *) echo "آرگومان ناشناخته: $arg" >&2; exit 2 ;;
    esac
done

PASSED=0
FAILED=0
section() { printf '\n\033[1;34m━━━ %s ━━━\033[0m\n' "$*"; }
pass() { PASSED=$((PASSED + 1)); printf '  \033[32m✔ PASS\033[0m  %s\n' "$*"; }
fail() { FAILED=$((FAILED + 1)); printf '  \033[31m✘ FAIL\033[0m  %s\n' "$*"; }
info() { printf '          %s\n' "$*"; }
k() { kubectl -n "$NAMESPACE" "$@"; }

# پایتون میزبان فقط برای خواندن JSON (python3 ویندوز گاهی فقط میان‌بر Microsoft Store است)
PYTHON=""
for candidate in python3 python; do
    if "$candidate" -c "import json" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
[[ -n "$PYTHON" ]] || { echo "Python روی این سیستم پیدا نشد" >&2; exit 2; }

# اجرای psql داخل Pod پستگرس (SQL از stdin) — <database>
psql_exec() {
    k exec -i postgres-0 -c postgres -- sh -c 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"' _ "$1"
}

# درخواست HTTP از داخل یک Pod بک‌اند (ایمیج curl ندارد؛ با خودِ پایتون) — <pod> <url>
backend_get() {
    k exec "$1" -c backend-api -- python -c \
        "import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1], timeout=5).read().decode())" "$2"
}

ready_checks_ok() {  # خروجی /health/ready → database و redis هر دو ok
    "$PYTHON" -c "import json, sys; c = json.loads(sys.argv[1])['checks']; sys.exit(0 if c.get('database') == 'ok' and c.get('redis') == 'ok' else 1)" "$1" 2>/dev/null
}

wait_postgres_ready() {  # <old-uid> — تا ساخته شدن Pod جدید (UID متفاوت) و Ready شدن آن
    local old_uid="$1" deadline=$((SECONDS + 300)) uid
    while ((SECONDS < deadline)); do
        uid="$(k get pod postgres-0 -o jsonpath='{.metadata.uid}' 2>/dev/null || true)"
        if [[ -n "$uid" && "$uid" != "$old_uid" ]] && k wait --for=condition=Ready pod/postgres-0 --timeout=5s >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

printf '\033[1mATS Smart — بررسی معیارهای پذیرش Kubernetes\033[0m\n'
printf 'context: %s · namespace: %s · %s\n' "$(kubectl config current-context)" "$NAMESPACE" "$(date '+%Y-%m-%d %H:%M:%S %Z')"

# =============================================================================
section "معیار ۱: استقرار هر ۱۰ سرویس و وضعیت Running همه‌ی Pod ها"
# =============================================================================
printf '  %-26s %-12s %-8s %s\n' SERVICE KIND READY IMAGE
for workload in deployment/backend-api deployment/worker deployment/scheduler deployment/frontend \
    statefulset/postgres deployment/redis deployment/prometheus deployment/alertmanager deployment/grafana deployment/backup; do
    data="$(k get "$workload" -o jsonpath='{.spec.replicas}|{.status.readyReplicas}|{.spec.template.spec.containers[0].image}' 2>/dev/null || true)"
    IFS='|' read -r desired ready image <<<"$data"
    ready="${ready:-0}"
    printf '  %-26s %-12s %-8s %s\n' "${workload#*/}" "${workload%%/*}" "${ready}/${desired:-?}" "$image"
    if [[ -n "${desired:-}" && "$desired" -ge 1 && "$ready" == "$desired" ]]; then
        pass "${workload}: ${ready}/${desired} نسخه آماده"
    else
        fail "${workload}: ${ready}/${desired:-?} نسخه آماده"
    fi
done

ds="$(k get daemonset node-exporter -o jsonpath='{.status.desiredNumberScheduled}|{.status.numberReady}' 2>/dev/null || true)"
IFS='|' read -r ds_desired ds_ready <<<"$ds"
[[ -n "${ds_desired:-}" && "$ds_desired" == "${ds_ready:-}" ]] \
    && pass "daemonset/node-exporter (Agent): ${ds_ready}/${ds_desired} Node" \
    || fail "daemonset/node-exporter: ${ds_ready:-0}/${ds_desired:-?}"

migrate="$(k get job migrate -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
if [[ "$migrate" == "1" ]]; then
    pass "job/migrate: مایگریشن‌ها با موفقیت اجرا شدند (Completed)"
elif ! k get job migrate >/dev/null 2>&1; then
    pass "job/migrate: پس از اجرای موفق توسط TTL پاک شده (بک‌اند فقط پس از head بالا می‌آید)"
else
    fail "job/migrate هنوز کامل نشده"
fi

# همه‌ی Pod ها به‌جز Pod های Job های تمام‌شده (Succeeded) باید Running و همه‌ی کانتینرهایشان Ready باشند
not_ok="$(k get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.phase}{" "}{range .status.containerStatuses[*]}{.ready}{","}{end}{"\n"}{end}' \
    | awk '$2 != "Succeeded" && ($2 != "Running" || $3 ~ /false/) {print $1 " (" $2 ")"}')"
running="$(k get pods --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if [[ -z "$not_ok" ]]; then
    pass "همه‌ی ${running} Pod در حال اجرا Running و Ready هستند"
else
    fail "Pod های ناسالم: $(echo "$not_ok" | tr '\n' ' ')"
fi
restarts="$(k get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{range .status.containerStatuses[*]}{.restartCount}{" "}{end}{"\n"}{end}' \
    | awk '{s = 0; for (i = 2; i <= NF; i++) s += $i; if (s > 0) print $1 "=" s}')"
[[ -z "$restarts" ]] && info "هیچ کانتینری ری‌استارت نشده" || info "ری‌استارت‌ها: $(echo "$restarts" | tr '\n' ' ')"
echo
k get pods -o wide | sed 's/^/  /'

# =============================================================================
section "معیار ۲: ارتباط پایدار شبکه‌ی داخلی (بک‌اند ↔ دیتابیس ↔ کش)"
# =============================================================================
mapfile -t backend_pods < <(k get pods -l app.kubernetes.io/name=backend-api --field-selector=status.phase=Running -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
worker_pod="$(k get pods -l app.kubernetes.io/name=worker --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')"
frontend_pod="$(k get pods -l app.kubernetes.io/name=frontend --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')"

# ۲-۱: DNS داخلی کلاستر — هر نام Service باید به ClusterIP همان Service برسد
dns_output="$(k exec "${backend_pods[0]}" -c backend-api -- python -c '
import socket
for name in ("postgres", "redis", "backend-api", "frontend", "prometheus", "postgres-0.postgres-headless"):
    try:
        print(name, socket.gethostbyname(name))
    except OSError as error:
        print(name, "ERROR", error)
' 2>&1)"
dns_failed=0
while read -r name address _; do
    expected="$(k get svc "$name" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)"
    [[ "$name" == postgres-0.* ]] && expected="$(k get pod postgres-0 -o jsonpath='{.status.podIP}')"
    if [[ "$address" == "$expected" ]]; then
        info "DNS  ${name} → ${address}"
    else
        info "DNS  ${name} → ${address} (انتظار: ${expected})"
        dns_failed=1
    fi
done <<<"$dns_output"
((dns_failed == 0)) && pass "DNS داخلی: همه‌ی نام‌های سرویس به IP درست resolve شدند" || fail "DNS داخلی"

# ۲-۲: هر نسخه‌ی بک‌اند ← PostgreSQL و Redis (بررسی عمیق /api/v1/health/ready)
for pod in "${backend_pods[@]}"; do
    response="$(backend_get "$pod" http://127.0.0.1:8000/api/v1/health/ready 2>&1)"
    if ready_checks_ok "$response"; then
        pass "${pod} → PostgreSQL و Redis: ${response}"
    else
        fail "${pod} → ${response}"
    fi
done

# ۲-۳: Worker ← PostgreSQL (کوئری واقعی با asyncpg) و Redis (PING + ثبت Worker در صف RQ)
worker_output="$(k exec "$worker_pod" -c worker -- python -c '
import asyncio, os
import asyncpg, redis
from rq import Worker

async def db():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""), timeout=5)
    try:
        return await conn.fetchval("select count(*) from users")
    finally:
        await conn.close()

client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_timeout=5)
print("postgres=ok users=%s" % asyncio.run(db()))
print("redis=%s rq_workers=%d" % ("ok" if client.ping() else "fail", len(Worker.all(connection=client))))
' 2>&1)"
if grep -q "postgres=ok" <<<"$worker_output" && grep -q "redis=ok" <<<"$worker_output"; then
    pass "${worker_pod} → $(echo "$worker_output" | tr '\n' ' ')"
else
    fail "${worker_pod} → ${worker_output}"
fi

# ۲-۴: مسیر کامل کاربر داخل کلاستر: فرانت‌اند (Nginx) → Service backend-api → PostgreSQL/Redis
probe="$(k exec "$frontend_pod" -c frontend -- sh -c '
ok=0; fail=0
for i in $(seq 1 200); do
    if wget -q -T 5 -O - http://127.0.0.1/api/v1/health/ready 2>/dev/null | grep -q "\"database\":\"ok\",\"redis\":\"ok\""; then
        ok=$((ok + 1)); else fail=$((fail + 1)); fi
done
echo "$ok $fail"' 2>&1)"
read -r probe_ok probe_fail <<<"$probe"
if [[ "${probe_fail:-x}" == "0" ]]; then
    pass "فرانت‌اند → بک‌اند → دیتابیس/کش: ${probe_ok}/200 درخواست پیاپی موفق، ۰ خطا"
else
    fail "فرانت‌اند → بک‌اند: ${probe_ok:-0} موفق، ${probe_fail:-?} ناموفق (${probe})"
fi

# ۲-۵: پخش بار بین نسخه‌های بک‌اند — شمارنده‌ی درخواست‌های هر Pod (متریک Prometheus خودِ برنامه)
if ((${#backend_pods[@]} > 1)); then
    served=0
    for pod in "${backend_pods[@]}"; do
        count="$(backend_get "$pod" http://127.0.0.1:8000/metrics 2>/dev/null \
            | awk '/^http_requests_total\{/ && /health\/ready/ {sum += $NF} END {printf "%d", sum}')"
        info "${pod}: ${count:-0} درخواست /health/ready پاسخ داده"
        [[ "${count:-0}" -gt 0 ]] && served=$((served + 1))
    done
    ((served == ${#backend_pods[@]})) \
        && pass "Service backend-api بار را بین هر ${#backend_pods[@]} نسخه‌ی بک‌اند پخش کرده است" \
        || fail "فقط ${served} از ${#backend_pods[@]} نسخه‌ی بک‌اند درخواست گرفته‌اند"
fi

# ۲-۶: از بیرون کلاستر (مرورگر کاربر) — NGINX Ingress Controller
if [[ "$OVERLAY" == "local" ]] && command -v curl >/dev/null; then
    external="$(curl -s -m 5 http://localhost:8081/api/v1/health/ready || true)"
    ready_checks_ok "$external" && pass "http://localhost:8081 (NGINX Ingress) → ${external}" || fail "http://localhost:8081 → ${external:-بدون پاسخ}"
fi

# ۲-۷: Prometheus همه‌ی اهداف را از طریق شبکه‌ی داخلی Scrape می‌کند (up == 1)
targets="$(k exec deploy/prometheus -c prometheus -- wget -qO- 'http://127.0.0.1:9090/api/v1/query?query=up' 2>/dev/null \
    | "$PYTHON" -c '
import json, sys
for r in json.load(sys.stdin)["data"]["result"]:
    m = r["metric"]
    print(m.get("job"), m.get("pod", m.get("instance")), r["value"][1])' 2>/dev/null)"
down="$(awk '$3 != "1"' <<<"$targets")"
while read -r job target value; do [[ -n "$job" ]] && info "Prometheus  ${job} ${target}  up=${value}"; done <<<"$targets"
[[ -n "$targets" && -z "$down" ]] && pass "همه‌ی $(wc -l <<<"$targets" | tr -d ' ') هدف Prometheus در دسترس (up=1)" || fail "اهداف در دسترس نیستند: ${down:-خروجی خالی}"

# ۲-۸: هیچ خطای اتصال بین سرویس‌های داخلی در لاگ کانتینرهای اصلی (نه initContainer های «در انتظار ...»).
# فقط خطاهای PostgreSQL/Redis/DNS شمرده می‌شوند؛ خطای SMTP (سرویس بیرونی ایمیل که در محیط لوکال
# تنظیم نشده) معیار شبکه‌ی داخلی نیست
pattern='redis\.exceptions\.(connection|timeout)error|connecting to redis|asyncpg\.exceptions|connection to server at|could not connect to server|operationalerror|connectiondoesnotexisterror|cannotconnectnowerror|name or service not known|temporary failure in name resolution|connection reset by peer'
errors=0
for pod in "${backend_pods[@]}" "$worker_pod" $(k get pods -l app.kubernetes.io/name=scheduler -o name | cut -d/ -f2); do
    container="$(k get pod "$pod" -o jsonpath='{.spec.containers[0].name}')"
    count="$(k logs "$pod" -c "$container" 2>/dev/null | grep -ciE "$pattern" || true)"
    info "لاگ ${pod}: ${count} خطای اتصال"
    errors=$((errors + count))
done
((errors == 0)) && pass "هیچ خطای اتصال PostgreSQL/Redis/DNS در لاگ‌های بک‌اند، Worker و Scheduler" || fail "${errors} خطای اتصال در لاگ‌ها"

# =============================================================================
section "معیار ۳: ماندگاری داده‌ی PostgreSQL روی Persistent Volume"
# =============================================================================
pvc_line() { k get pvc "$1" -o jsonpath='{.metadata.name} → {.spec.volumeName} ({.status.phase}، {.spec.storageClassName}، {.status.capacity.storage})'; }
info "$(pvc_line data-postgres-0)"
info "$(pvc_line wal-archive-postgres-0)"
pv_name="$(k get pvc data-postgres-0 -o jsonpath='{.spec.volumeName}')"
info "PV ${pv_name}: reclaimPolicy=$(kubectl get pv "$pv_name" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}') مسیر=$(kubectl get pv "$pv_name" -o jsonpath='{.spec.hostPath.path}{.spec.csi.volumeHandle}')"

if ((DISRUPT == 0)); then
    info "(--no-disruption: آزمون حذف Pod اجرا نشد)"
else
    # نشانگر در دیتابیس جدای k8s_persistence_check — به جداول برنامه و مایگریشن‌های Alembic دست نمی‌زند
    if [[ "$(echo "select 1 from pg_database where datname = 'k8s_persistence_check'" | psql_exec postgres)" != "1" ]]; then
        echo "create database k8s_persistence_check" | psql_exec postgres
    fi
    token="k8s-$(date +%Y%m%d-%H%M%S)-${RANDOM}"
    old_uid="$(k get pod postgres-0 -o jsonpath='{.metadata.uid}')"
    psql_exec k8s_persistence_check <<SQL
create table if not exists marker (id serial primary key, token text not null, pod_uid text not null, written_at timestamptz not null default now());
insert into marker (token, pod_uid) values ('${token}', '${old_uid}');
SQL
    users_before="$(echo "select count(*) from users" | psql_exec smart_ats_db)"
    info "نشانگر نوشته شد: ${token} (Pod UID ${old_uid}) · تعداد کاربران برنامه: ${users_before}"

    verify_marker() {  # <scenario>
        local found users_after new_uid new_pv
        new_uid="$(k get pod postgres-0 -o jsonpath='{.metadata.uid}')"
        new_pv="$(k get pvc data-postgres-0 -o jsonpath='{.spec.volumeName}')"
        found="$(echo "select count(*) from marker where token = '${token}'" | psql_exec k8s_persistence_check 2>&1)"
        users_after="$(echo "select count(*) from users" | psql_exec smart_ats_db 2>&1)"
        info "Pod جدید: UID ${new_uid} · PV: ${new_pv} · کاربران: ${users_after}"
        if [[ "$found" == "1" && "$new_pv" == "$pv_name" && "$users_after" == "$users_before" && "$new_uid" != "$old_uid" ]]; then
            pass "$1: Pod جدید (UID متفاوت) به همان PV وصل شد و نشانگر ${token} و همه‌ی ${users_after} کاربر سالم ماندند"
        else
            fail "$1: نشانگر=${found} PV=${new_pv} (انتظار ${pv_name}) کاربران=${users_after}/${users_before}"
        fi
        old_uid="$new_uid"
    }

    # سناریوی الف: از کار افتادن Pod — StatefulSet آن را با همان نام و همان PVC دوباره می‌سازد
    started=$SECONDS
    k delete pod postgres-0 --wait=true >/dev/null
    if wait_postgres_ready "$old_uid"; then
        info "Pod postgres-0 پس از $((SECONDS - started)) ثانیه دوباره Ready شد"
        verify_marker "سناریوی الف (حذف Pod)"
    else
        fail "سناریوی الف: postgres-0 در ۵ دقیقه Ready نشد"
    fi

    # سناریوی ب (--deep): حذف کامل StatefulSet — PVC طبق persistentVolumeClaimRetentionPolicy باقی می‌ماند
    if ((DEEP == 1)); then
        release_dir="k8s/.release/${OVERLAY}"
        [[ -f "${release_dir}/kustomization.yaml" ]] || release_dir="k8s/overlays/${OVERLAY}"
        started=$SECONDS
        k delete statefulset postgres --wait=true >/dev/null
        k wait --for=delete pod/postgres-0 --timeout=120s >/dev/null 2>&1 || true
        info "StatefulSet حذف شد؛ PVC: $(k get pvc data-postgres-0 -o jsonpath='{.status.phase}') — ساخت دوباره از ${release_dir}"
        kubectl apply -k "$release_dir" >/dev/null
        if wait_postgres_ready "$old_uid"; then
            info "StatefulSet جدید پس از $((SECONDS - started)) ثانیه Ready شد"
            verify_marker "سناریوی ب (حذف و ساخت دوباره‌ی StatefulSet)"
        else
            fail "سناریوی ب: postgres-0 در ۵ دقیقه Ready نشد"
        fi
    fi

    info "تاریخچه‌ی نشانگرها (اجراهای قبلی این اسکریپت هم باید باقی مانده باشند):"
    echo "select id, token, written_at from marker order by id" | psql_exec k8s_persistence_check | sed 's/^/            /'

    # برنامه پس از ری‌استارت دیتابیس بدون دخالت دستی دوباره وصل می‌شود (pool_pre_ping)
    reconnected=0
    for _ in $(seq 1 15); do
        response="$(backend_get "${backend_pods[0]}" http://127.0.0.1:8000/api/v1/health/ready 2>/dev/null || true)"
        ready_checks_ok "$response" && { reconnected=1; break; }
        sleep 2
    done
    ((reconnected == 1)) && pass "بک‌اند پس از بازگشت دیتابیس خودکار دوباره وصل شد: ${response}" || fail "بک‌اند دوباره به دیتابیس وصل نشد"
fi

# =============================================================================
section "اطلاعات تکمیلی: مقیاس‌دهی خودکار و منابع"
# =============================================================================
k get hpa 2>/dev/null | sed 's/^/  /'
echo
kubectl top pods -n "$NAMESPACE" 2>/dev/null | sed 's/^/  /' || info "metrics-server در دسترس نیست"

# =============================================================================
printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED"
if ((FAILED == 0)); then
    printf '\033[1;32m[ACCEPTANCE PASS] همه‌ی معیارهای پذیرش برقرارند\033[0m\n'
    exit 0
fi
printf '\033[1;31m[ACCEPTANCE FAIL]\033[0m\n'
exit 1
