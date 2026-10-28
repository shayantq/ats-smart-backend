#!/usr/bin/env bash
# =============================================================================
# استقرار بدون قطعی (Zero-Downtime) نسخه‌ی جدید ATS Smart روی سرور Production.
#
# فراخوانی (معمولاً خودکار، از خط لوله‌ی CI/CD از طریق SSH):
#   BACKEND_IMAGE=user/ats-smart-backend:sha-abc1234 \
#   FRONTEND_IMAGE=user/ats-smart-frontend:sha-abc1234 \
#   ./deploy/deploy.sh
#
# مراحل:
#   ۱. کشیدن ایمیج‌های جدید از Docker Hub (سایت هنوز با نسخه‌ی قبلی کار می‌کند)
#   ۲. اطمینان از بالا بودن دیتابیس/Redis و اجرای مایگریشن‌ها
#   ۳. Rolling Update برای backend_api و frontend:
#        - کانتینرهای نسخه‌ی جدید «کنار» کانتینرهای قدیمی بالا می‌آیند
#        - تا وقتی Healthcheck نسخه‌ی جدید سبز نشده، قدیمی‌ها دست نمی‌خورند
#        - بعد قدیمی‌ها با SIGTERM به‌آرامی خاموش می‌شوند (درخواست‌های در حال اجرا
#          تمام می‌شوند) و Nginx (gateway/frontend) درخواست‌های جدید را به نسخه‌ی
#          جدید می‌فرستد — بنگرید توضیح resolver/proxy_next_upstream در gateway.conf
#        - اگر نسخه‌ی جدید سالم بالا نیاید: کانتینرهای جدید حذف، نسخه‌ی قبلی بدون
#          هیچ وقفه‌ای به کارش ادامه می‌دهد و اسکریپت با خطا خارج می‌شود (Rollback)
#   ۴. جایگزینی Worker/Scheduler صف (Warm Shutdown؛ کارهای صف در Redis منتظر می‌مانند)
#   ۵. به‌روزرسانی/بارگذاری مجدد پیکربندی مانیتورینگ و Gateway بدون ری‌استارت
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

: "${BACKEND_IMAGE:?BACKEND_IMAGE تنظیم نشده است}"
: "${FRONTEND_IMAGE:?FRONTEND_IMAGE تنظیم نشده است}"

HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"
RELEASE_ENV="deploy/release.env"
CANDIDATE_RELEASE_ENV="deploy/release.env.next"

log() { printf '\n\033[1;34m[deploy %s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '\n\033[1;31m[deploy %s] خطا:\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

if [[ ! -f "${ENV_FILE:-.env}" ]]; then
    fail "فایل ${ENV_FILE:-.env} در ${PROJECT_DIR} وجود ندارد (بنگرید .env.example و README بخش استقرار)."
fi

# Zero-Trust: کلید سرویس‌به‌سرویس Worker (ES256) — فقط یک‌بار و فقط روی خود سرور ساخته می‌شود؛ هرگز در
# ریپو، .env یا خروجی CI نیست. پوشه‌ی secrets فقط برای کاربر استقرار باز است؛ خود فایل‌ها برای کاربر
# داخل کانتینر (uid 10001) خواندنی‌اند. چرخش کلید: هر دو فایل را پاک و دوباره مستقر کنید.
ensure_service_keys() {
    local dir="secrets/service-auth"
    if [[ -f "${dir}/worker.key" && -f "${dir}/public/worker.pem" ]]; then
        return 0
    fi
    command -v openssl >/dev/null 2>&1 || fail "openssl روی سرور نصب نیست (برای ساخت کلید سرویس‌ها لازم است)."
    mkdir -p "${dir}/public"
    chmod 700 secrets "${dir}"
    (umask 077 && openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "${dir}/worker.key" 2>/dev/null)
    openssl pkey -in "${dir}/worker.key" -pubout -out "${dir}/public/worker.pem" 2>/dev/null
    chmod 444 "${dir}/worker.key" "${dir}/public/worker.pem"
    chmod 755 "${dir}/public"
    log "کلید سرویس Worker ساخته شد (secrets/service-auth) — فقط کلید عمومی در اختیار API است"
}
ensure_service_keys

# نسخه‌ی کاندید جدا نوشته می‌شود؛ فقط بعد از موفقیت کامل جای release.env را می‌گیرد،
# تا هر دستور دستی بعدی (deploy/compose.sh) همیشه نسخه‌ی «سالم» آخر را ببیند
cat > "${CANDIDATE_RELEASE_ENV}" <<EOF
BACKEND_IMAGE=${BACKEND_IMAGE}
FRONTEND_IMAGE=${FRONTEND_IMAGE}
DEPLOYED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

compose() {
    RELEASE_ENV_FILE="${CANDIDATE_RELEASE_ENV}" bash ./deploy/compose.sh "$@"
}

# نام پروژه‌ی Compose (پیش‌فرض ats-smart؛ با COMPOSE_PROJECT_NAME در .env قابل تغییر — مثلاً وقتی
# محیط Production کنار محیط Staging روی یک ماشین اجرا می‌شود)
PROJECT_NAME="$(compose config 2>/dev/null | sed -n 's/^name: //p' | head -n 1)"
[[ -n "${PROJECT_NAME}" ]] || fail "پیکربندی Compose نامعتبر است: ./deploy/compose.sh config"

# شناسه‌ی کانتینرهای در حال اجرای یک سرویس
service_containers() {
    docker ps -q \
        --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
        --filter "label=com.docker.compose.service=$1"
}

wait_until_healthy() {
    local container_id="$1"
    local waited=0
    while (( waited < HEALTH_TIMEOUT_SECONDS )); do
        local health
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_id}" 2>/dev/null || echo missing)"
        case "${health}" in
            healthy) return 0 ;;
            unhealthy | missing) return 1 ;;
        esac
        sleep 2
        waited=$((waited + 2))
    done
    return 1
}

# Rolling Update یک سرویس پشت Nginx — هسته‌ی استقرار بدون قطعی
rolling_update() {
    local service="$1"
    local old_ids new_ids old_count
    old_ids="$(service_containers "${service}")"
    old_count="$(grep -c . <<< "${old_ids}" || true)"

    if (( old_count == 0 )); then
        log "${service}: نسخه‌ی قبلی وجود ندارد (اولین استقرار) — راه‌اندازی مستقیم (تعداد نسخه‌ها: scale در compose)"
        compose up -d --no-deps --no-build "${service}"
        for container_id in $(service_containers "${service}"); do
            wait_until_healthy "${container_id}" || fail "${service} سالم بالا نیامد. لاگ: ./deploy/compose.sh logs ${service}"
        done
        return
    fi

    log "${service}: بالا آوردن ${old_count} کانتینر نسخه‌ی جدید کنار نسخه‌ی فعلی"
    compose up -d --no-deps --no-build --no-recreate --scale "${service}=$((old_count * 2))" "${service}"

    new_ids="$(comm -13 <(sort <<< "${old_ids}") <(service_containers "${service}" | sort))"
    [[ -n "${new_ids}" ]] || fail "${service}: کانتینر جدیدی ساخته نشد."

    for container_id in ${new_ids}; do
        if ! wait_until_healthy "${container_id}"; then
            log "${service}: نسخه‌ی جدید Healthcheck را پاس نکرد — Rollback (نسخه‌ی فعلی دست‌نخورده می‌ماند)"
            docker logs --tail 50 "${container_id}" >&2 || true
            # shellcheck disable=SC2086
            docker rm -f ${new_ids} > /dev/null
            fail "استقرار ${service} لغو شد."
        fi
    done

    # فرصت به Nginx تا با انقضای کش DNS (۵ ثانیه) کانتینرهای جدید را ببیند
    sleep 6

    log "${service}: خاموش‌کردن آرام (Graceful) نسخه‌ی قبلی"
    # shellcheck disable=SC2086
    docker stop --time 35 ${old_ids} > /dev/null
    # shellcheck disable=SC2086
    docker rm ${old_ids} > /dev/null

    # هماهنگ‌کردن وضعیت Compose با تعداد واقعی (بدون ساخت/حذف کانتینر دیگری)
    compose up -d --no-deps --no-build --no-recreate --scale "${service}=${old_count}" "${service}"
    log "${service}: ✔ به‌روزرسانی شد"
}

# -----------------------------------------------------------------------------
log "۱/۵ کشیدن ایمیج‌های نسخه‌ی جدید: ${BACKEND_IMAGE} | ${FRONTEND_IMAGE}"
# SKIP_PULL=1 فقط برای تست محلی اسکریپت با ایمیج‌هایی که در هیچ Registry نیستند
if [[ "${SKIP_PULL:-0}" != "1" ]]; then
    compose pull --quiet backend_api frontend
fi

log "۲/۵ اطمینان از سرویس‌های داده و اجرای مایگریشن‌ها"
compose up -d --no-deps --no-build --wait postgres_db redis_cache
# ⚠️ مایگریشن‌ها پیش از جایگزینی کد اجرا می‌شوند، پس برای حفظ «بدون قطعی» باید
# با نسخه‌ی قبلی کد هم سازگار باشند (الگوی Expand/Contract — بنگرید README)
compose run --rm --no-deps migrate

log "۳/۵ Rolling Update بک‌اند و فرانت‌اند"
# پیکربندی جدید Gateway (توزیع بار، Timeoutها) باید «پیش از» جابه‌جایی نسخه‌ها فعال باشد —
# reload بدون قطع اتصال‌های جاری انجام می‌شود (worker های قدیمی nginx کارشان را تمام می‌کنند)
if [[ -n "$(service_containers gateway)" ]]; then
    compose exec -T gateway nginx -t > /dev/null 2>&1 || fail "پیکربندی جدید Gateway نامعتبر است (nginx -t)"
    compose exec -T gateway nginx -s reload > /dev/null
fi
rolling_update backend_api
rolling_update frontend

log "۴/۵ جایگزینی Worker و Scheduler صف"
compose up -d --no-deps --no-build worker scheduler

log "۵/۵ مانیتورینگ و Gateway"
compose up -d --no-deps --no-build \
    prometheus alertmanager grafana node_exporter postgres_exporter redis_exporter gateway
# ایمیج کوچک ابزار بک‌آپ روی خود سرور ساخته می‌شود (backup/Dockerfile)؛ کار در حال اجرا با قفل محافظت می‌شود.
# شبیه‌ساز Offsite فقط اگر پروفایل local-offsite فعال باشد (محیط بدون Offsite واقعی)
if compose config --services | grep -qx offsite_storage; then
    compose up -d --no-deps --build offsite_storage
fi
compose up -d --no-deps --build backup
# پیکربندی‌های mount‌شده (prometheus.yml، alerts.yml، gateway.conf ...) بدون ری‌استارت بارگذاری مجدد می‌شوند
compose kill -s HUP prometheus alertmanager > /dev/null 2>&1 || true
compose exec -T gateway nginx -s reload > /dev/null 2>&1 || true

mv "${CANDIDATE_RELEASE_ENV}" "${RELEASE_ENV}"

# ایمیج‌های بلااستفاده‌ی قدیمی‌تر از ۷ روز (نسخه‌های اخیر برای Rollback دستی می‌مانند).
# PRUNE_IMAGES=0 روی ماشینی که پروژه‌های دیگری هم دارد (مثلاً Runner محلی)
if [[ "${PRUNE_IMAGES:-1}" == "1" ]]; then
    docker image prune -af --filter "until=168h" > /dev/null || true
fi

log "✅ استقرار با موفقیت انجام شد"
compose ps
