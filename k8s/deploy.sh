#!/usr/bin/env bash
# =============================================================================
# استقرار ATS Smart روی Kubernetes (پیش‌فرض: Overlay محیط لوکال Docker Desktop)
#
#   bash k8s/deploy.sh                 استقرار/به‌روزرسانی کامل
#   OVERLAY=local bash k8s/deploy.sh   انتخاب Overlay (پوشه‌ای در k8s/overlays)
#   IMAGE_TAG=sha-1a2b3c4 ...          تگ ایمیج دلخواه (پیش‌فرض: sha کامیت جاری)
#   FORCE_BUILD=1 ...                  ساخت دوباره‌ی ایمیج‌ها حتی اگر همین تگ موجود باشد
#   SKIP_BUILD=1 ...                   بدون ساخت ایمیج (همان تگ‌های :local داخل Overlay)
#   SKIP_ADDONS=1 ...                  بدون نصب/به‌روزرسانی metrics-server و NGINX Ingress Controller
#
# مراحل: بررسی کلاستر ← ساخت Secret های محلی (فقط بار اول) ← ساخت ایمیج‌ها ← metrics-server و Ingress Controller
#        ← اعمال مانیفست‌ها ← انتظار برای مایگریشن و Rollout همه‌ی سرویس‌ها ← خلاصه‌ی وضعیت
# =============================================================================
set -euo pipefail

# Git Bash ویندوز آرگومان‌های شبیه مسیر (مثل /api/v1/health) را به مسیر ویندوزی تبدیل می‌کند
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

OVERLAY="${OVERLAY:-local}"
NAMESPACE="${NAMESPACE:-ats-smart}"
OVERLAY_DIR="k8s/overlays/${OVERLAY}"
RELEASE_DIR="k8s/.release/${OVERLAY}"
SECRETS_DIR="${OVERLAY_DIR}/secrets"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-600s}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok() { printf '    \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

random_secret() { head -c "${1:-24}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

[[ -d "$OVERLAY_DIR" ]] || die "Overlay «${OVERLAY}» در ${OVERLAY_DIR} وجود ندارد"

# -----------------------------------------------------------------------------
log "۱/۷ بررسی دسترسی به کلاستر"
CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
[[ -n "$CONTEXT" ]] || die "هیچ context ی برای kubectl تنظیم نشده (Docker Desktop: Settings ← Kubernetes ← Enable)"
kubectl get --raw /readyz >/dev/null 2>&1 || die "API Server کلاستر «${CONTEXT}» در دسترس نیست"
# Overlay لوکال (ایمیج‌های محلی، Offsite شبیه‌سازی‌شده) هرگز اشتباهی روی کلاستر واقعی اعمال نشود
if [[ "$OVERLAY" == "local" && "$CONTEXT" != "docker-desktop" && "${ALLOW_ANY_CONTEXT:-0}" != "1" ]]; then
    die "Overlay لوکال فقط برای context «docker-desktop» است (فعلی: ${CONTEXT}) — در صورت اطمینان: ALLOW_ANY_CONTEXT=1"
fi
ok "context: ${CONTEXT} · نسخه‌ی سرور: $(kubectl version -o json 2>/dev/null | grep -m1 -o '"gitVersion": *"[^"]*"' | tail -1 | cut -d'"' -f4)"

# -----------------------------------------------------------------------------
log "۲/۷ Secret ها (${SECRETS_DIR})"
umask 077
if [[ ! -f "${SECRETS_DIR}/postgres.env" ]]; then
    db_password="$(random_secret 24)"
    cat > "${SECRETS_DIR}/postgres.env" <<EOF
POSTGRES_USER=ats
POSTGRES_PASSWORD=${db_password}
EOF
    cat > "${SECRETS_DIR}/backend.env" <<EOF
DATABASE_URL=postgresql+asyncpg://ats:${db_password}@postgres:5432/smart_ats_db
SECRET_KEY=$(random_secret 32)
OPS_WEBHOOK_TOKEN=$(random_secret 32)
SMTP_USERNAME=
SMTP_PASSWORD=
S3_ACCESS_KEY=
S3_SECRET_KEY=
EOF
    ok "postgres.env و backend.env با رمزهای تصادفی ساخته شدند"
fi
if [[ ! -f "${SECRETS_DIR}/grafana.env" ]]; then
    printf 'GF_SECURITY_ADMIN_USER=admin\nGF_SECURITY_ADMIN_PASSWORD=%s\n' "$(random_secret 12)" > "${SECRETS_DIR}/grafana.env"
    ok "grafana.env ساخته شد (رمز ورود Grafana داخل همین فایل است)"
fi
# هوش مصنوعی مولد: بدون تنظیم، قابلیت غیرفعال می‌ماند (نمونه و راهنما: genai.env.example)
if [[ ! -f "${SECRETS_DIR}/genai.env" ]]; then
    cat > "${SECRETS_DIR}/genai.env" <<EOF
GENAI_BASE_URL=
GENAI_MODEL=
GENAI_API_KEY=
GENAI_STRUCTURED_OUTPUT=json_schema
EOF
    ok "genai.env (خالی — تولید سؤال مصاحبه غیرفعال؛ راهنما: genai.env.example)"
fi
# Zero-Trust: جفت‌کلید ES256 سرویس هوش مصنوعی (genai-worker ← API با X-Internal-Auth) — یک‌بار و فقط
# روی همین سیستم ساخته می‌شود (در .gitignore)؛ چرخش کلید: هر دو فایل را پاک و دوباره مستقر کنید
SERVICE_AUTH_DIR="${SECRETS_DIR}/service-auth"
if [[ ! -f "${SERVICE_AUTH_DIR}/genai-worker.key" || ! -f "${SERVICE_AUTH_DIR}/genai-worker.pem" ]]; then
    command -v openssl >/dev/null 2>&1 || { echo "openssl پیدا نشد (برای ساخت کلید سرویس‌ها لازم است)" >&2; exit 1; }
    mkdir -p "${SERVICE_AUTH_DIR}"
    (umask 077 && openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "${SERVICE_AUTH_DIR}/genai-worker.key" 2>/dev/null)
    openssl pkey -in "${SERVICE_AUTH_DIR}/genai-worker.key" -pubout -out "${SERVICE_AUTH_DIR}/genai-worker.pem" 2>/dev/null
    ok "کلید سرویس genai-worker ساخته شد (secrets/service-auth) — API فقط کلید عمومی را می‌گیرد"
fi
# حریم خصوصی: کلیدهای رمزنگاری داده‌های شخصی — یک‌بار و فقط روی همین سیستم (در .gitignore)؛ هرگز چاپ نمی‌شوند.
# گم شدن این فایل = غیرقابل‌خواندن شدن داده‌های رمزشده‌ی دیتابیس کلاستر
if [[ ! -s "${SECRETS_DIR}/pii.env" ]]; then
    command -v openssl >/dev/null 2>&1 || { echo "openssl پیدا نشد (برای ساخت کلید رمزنگاری لازم است)" >&2; exit 1; }
    (
        umask 077
        {
            echo "PII_ENCRYPTION_KEYS=$(openssl rand -base64 32 | tr '+/' '-_')"
            echo "PII_BLIND_INDEX_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
        } > "${SECRETS_DIR}/pii.env"
    )
    ok "کلیدهای رمزنگاری داده‌های شخصی ساخته شد (secrets/pii.env) — یک نسخه را جدا نگه دارید"
fi
for name in postgres backend grafana; do
    [[ -f "${SECRETS_DIR}/${name}.env" ]] || die "فایل ${SECRETS_DIR}/${name}.env وجود ندارد (نمونه: ${name}.env.example)"
done
umask 022

# -----------------------------------------------------------------------------
log "۳/۷ ایمیج‌ها"
if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
    IMAGE_TAG=""
    warn "SKIP_BUILD=1 — همان تگ‌های داخل ${OVERLAY_DIR}/kustomization.yaml"
else
    IMAGE_TAG="${IMAGE_TAG:-sha-$(git rev-parse --short HEAD)}"
    if [[ -n "$(git status --porcelain -- app alembic frontend backup Dockerfile requirements.txt 2>/dev/null)" ]]; then
        warn "تغییرات Commit‌نشده در کد برنامه — برای ساختن ایمیج از همین کد: FORCE_BUILD=1"
    fi
    build_image() {  # <name> <context> [build-args...]
        local image="$1:${IMAGE_TAG}" context="$2"
        shift 2
        if [[ "${FORCE_BUILD:-0}" != "1" ]] && docker image inspect "$image" >/dev/null 2>&1; then
            ok "${image} (موجود)"
            return
        fi
        echo "    ساخت ${image} ..."
        docker build -q -t "$image" "$@" "$context" >/dev/null
        ok "${image} (ساخته شد)"
    }
    build_image ats-smart-backend . --build-arg "APP_VERSION=${IMAGE_TAG}" ${DEBIAN_MIRROR:+--build-arg "DEBIAN_MIRROR=${DEBIAN_MIRROR}"}
    build_image ats-smart-frontend frontend
    build_image ats-smart-backup backup
fi

# کلید عمومی رمزنگاری بک‌آپ (همان کلید نسخه‌ی Compose؛ اگر نبود، یک جفت‌کلید تازه)
if [[ ! -f "${SECRETS_DIR}/backup.env" ]]; then
    recipient_file="backup/secrets/public/age-recipient.txt"
    if [[ ! -s "$recipient_file" ]]; then
        mkdir -p backup/secrets/public backup/secrets/private
        docker run --rm --entrypoint age-keygen "ats-smart-backup:${IMAGE_TAG:-local}" > backup/secrets/private/age-identity.txt 2>/dev/null
        grep -o 'age1[0-9a-z]*' backup/secrets/private/age-identity.txt > "$recipient_file"
        warn "جفت‌کلید بک‌آپ تازه ساخته شد — کلید خصوصی backup/secrets/private/age-identity.txt را جای امنی نگه دارید"
    fi
    (umask 077 && cat > "${SECRETS_DIR}/backup.env" <<EOF
BACKUP_AGE_RECIPIENT=$(head -1 "$recipient_file" | tr -d '\r\n')
RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID=
RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY=
OFFSITE_SFTP_PASSWORD=
EOF
    )
    ok "backup.env با کلید عمومی ${recipient_file} ساخته شد"
fi

# Overlay انتشار: همان Overlay محیط + تگ ایمیج همین انتشار (معادل kustomize edit set image)
mkdir -p "$RELEASE_DIR"
{
    echo "# تولیدشده توسط k8s/deploy.sh — دستی ویرایش نکنید (در .gitignore)"
    echo "apiVersion: kustomize.config.k8s.io/v1beta1"
    echo "kind: Kustomization"
    echo "resources:"
    echo "  - ../../overlays/${OVERLAY}"
    if [[ -n "$IMAGE_TAG" ]]; then
        echo "images:"
        for image in ats-smart-backend ats-smart-frontend ats-smart-backup; do
            printf '  - name: %s\n    newTag: %s\n' "$image" "$IMAGE_TAG"
        done
    fi
} > "${RELEASE_DIR}/kustomization.yaml"

# -----------------------------------------------------------------------------
log "۴/۷ افزونه‌های کلاستر"
if [[ "${SKIP_ADDONS:-0}" == "1" ]]; then
    warn "SKIP_ADDONS=1"
elif kubectl get apiservice v1beta1.metrics.k8s.io >/dev/null 2>&1; then
    ok "metrics-server از قبل نصب است"
else
    kubectl apply -k k8s/addons/metrics-server >/dev/null
    kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s >/dev/null \
        && ok "metrics-server نصب شد (HPA و kubectl top)" \
        || warn "metrics-server آماده نشد — HPA تا آماده شدنش فقط حداقل نسخه‌ها را نگه می‌دارد"
fi
# NGINX Ingress Controller: نسخه‌ی مخصوص Overlay (مثلاً پورت‌های لوکال) اگر وجود دارد، وگرنه نسخه‌ی عمومی
if [[ "${SKIP_ADDONS:-0}" != "1" ]]; then
    ingress_dir="k8s/overlays/${OVERLAY}/ingress-controller"
    [[ -d "$ingress_dir" ]] || ingress_dir="k8s/addons/nginx-ingress"
    kubectl apply -k "$ingress_dir" >/dev/null
    kubectl -n nginx-ingress rollout status deployment/nginx-ingress --timeout=180s >/dev/null         && ok "NGINX Ingress Controller آماده است (${ingress_dir})"         || die "NGINX Ingress Controller آماده نشد: kubectl -n nginx-ingress describe pods"
fi

# -----------------------------------------------------------------------------
log "۵/۷ اعمال مانیفست‌ها (${RELEASE_DIR})"
# Job تغییرناپذیر است: Job انتشار قبلی حذف می‌شود تا مایگریشن با ایمیج جدید دوباره اجرا شود
kubectl -n "$NAMESPACE" delete job migrate --ignore-not-found >/dev/null 2>&1 || true
# --prune فقط برای ConfigMap/Secret: نسخه‌های قدیمیِ هش‌دار (بی‌استفاده) پاک می‌شوند؛ PVC ها و
# Secret های دستی (مثل backup-restore-key، بدون برچسب part-of) هرگز هدف Prune نیستند
kubectl apply -k "$RELEASE_DIR" --prune -l app.kubernetes.io/part-of=ats-smart \
    --prune-allowlist=core/v1/ConfigMap --prune-allowlist=core/v1/Secret | sed 's/^/    /'

# -----------------------------------------------------------------------------
# سرور مدل زبانی داخل کلاستر (اختیاری، فقط وقتی نشانی وزن‌های مدل در model.env آن پوشه داده شده)
genai_dir="${OVERLAY_DIR}/genai-inference"
if [[ -f "${genai_dir}/model.env" ]] && grep -qE '^MODEL_URL=.+' "${genai_dir}/model.env"; then
    kubectl apply -k "$genai_dir" | sed 's/^/    /'
    warn "سرور مدل زبانی اعمال شد؛ دانلود اول وزن‌ها ممکن است چند دقیقه طول بکشد: kubectl -n ${NAMESPACE} logs -f deploy/genai-inference -c fetch-model"
fi

log "۶/۷ انتظار برای آماده شدن سرویس‌ها"
kubectl -n "$NAMESPACE" rollout status statefulset/postgres --timeout="$ROLLOUT_TIMEOUT" >/dev/null
ok "postgres (StatefulSet)"
deadline=$((SECONDS + 600))
while true; do
    succeeded="$(kubectl -n "$NAMESPACE" get job migrate -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
    failed="$(kubectl -n "$NAMESPACE" get job migrate -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null || true)"
    [[ "$succeeded" == "1" ]] && break
    if [[ "$failed" == "True" || $SECONDS -gt $deadline ]]; then
        kubectl -n "$NAMESPACE" logs job/migrate --all-containers --tail=50 || true
        die "اجرای مایگریشن‌ها ناموفق بود"
    fi
    sleep 3
done
ok "migrate (Job): مایگریشن‌ها تا head اجرا شدند"
workloads=(deployment/redis deployment/backend-api deployment/worker deployment/resume-worker deployment/genai-worker
    deployment/scheduler deployment/frontend deployment/prometheus deployment/alertmanager deployment/grafana
    deployment/kube-state-metrics deployment/backup daemonset/node-exporter)
# سرویس‌های مخصوص یک Overlay (مثلاً Mailpit محیط لوکال)
kubectl -n "$NAMESPACE" get deployment mailpit >/dev/null 2>&1 && workloads+=(deployment/mailpit)
for workload in "${workloads[@]}"; do
    if ! kubectl -n "$NAMESPACE" rollout status "$workload" --timeout="$ROLLOUT_TIMEOUT" >/dev/null; then
        kubectl -n "$NAMESPACE" describe "$workload" | tail -20
        die "${workload} در زمان مقرر آماده نشد"
    fi
    ok "$workload"
done

# -----------------------------------------------------------------------------
log "۷/۷ وضعیت نهایی"
kubectl -n "$NAMESPACE" get pods -o wide
echo
kubectl -n "$NAMESPACE" get svc,pvc
if [[ "$OVERLAY" == "local" ]]; then
    cat <<EOF

    سایت:     http://localhost:8081   (NGINX Ingress)
    Grafana:  http://localhost:3030   (کاربر/رمز: ${SECRETS_DIR}/grafana.env)
    Prometheus: kubectl -n ${NAMESPACE} port-forward svc/prometheus 9091:9090  ←  http://localhost:9091
    بررسی معیارهای پذیرش: bash k8s/verify.sh · تست بار و HPA: bash k8s/hpa-stress.sh
EOF
fi
