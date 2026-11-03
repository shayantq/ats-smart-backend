#!/usr/bin/env bash
# =============================================================================
# ساخت و اعتبارسنجی دیتاست آموزش تکمیلی روی سرور Production (docs/finetune/DATASET.md):
#
#   cd /opt/ats-smart && TOKENIZER_URL='<نشانی مستقیم tokenizer.json مدل پایه>' bash deploy/finetune-dataset.sh
#   bash deploy/finetune-dataset.sh --min-pairs 10000                      # پارامترهای اضافه به build می‌رسند
#
#   ۱. توکنایزر: datasets/tokenizer/tokenizer.json؛ اگر نبود با TOKENIZER_URL یک‌بار دانلود می‌شود، وگرنه دستور
#      scp از ویندوز چاپ می‌شود. با TOKENIZER_SHA256 هش فایل پیش از استفاده بررسی می‌شود.
#   ۲. build داخل یک کانتینر یک‌بارمصرف از ایمیج backend (همان کلیدهای secrets/pii.env، تراکنش فقط‌خواندنی).
#   ۳. validate روی همان خروجی؛ هر خطا = کد خروج غیرصفر و تغییر نام خروجی به dataset.FAILED (برای آموزش نیست).
#   ۴. خروجی: datasets/finetune-<زمان>/dataset با دسترسی 700/600 — بیرون از هر پوشه‌ی وب.
#
# فقط شمارش‌ها و کد خطاها چاپ می‌شوند؛ هیچ متنی از رکوردها در خروجی یا لاگ نمی‌آید.
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

DATASETS_DIR="${PROJECT_DIR}/datasets"
TOKENIZER_DIR="${DATASETS_DIR}/tokenizer"
TOKENIZER_FILE="${TOKENIZER_DIR}/tokenizer.json"
RUN_DIR="${DATASETS_DIR}/finetune-$(date +%Y%m%d%H%M%S)-$$"
CONTAINER_UID=10001
MAX_TOKENS="${MAX_TOKENS:-4096}"

compose() { bash deploy/compose.sh "$@"; }

ensure_tokenizer() {
    mkdir -p "${TOKENIZER_DIR}"
    if [[ -s "${TOKENIZER_FILE}" ]]; then
        return 0
    fi
    if [[ -n "${TOKENIZER_URL:-}" ]]; then
        echo "دانلود توکنایزر ..."
        if curl -fsSL --retry 3 --retry-delay 5 -o "${TOKENIZER_FILE}.part" "${TOKENIZER_URL}"; then
            mv "${TOKENIZER_FILE}.part" "${TOKENIZER_FILE}"
            chmod 644 "${TOKENIZER_FILE}"
            return 0
        fi
        rm -f "${TOKENIZER_FILE}.part"
        echo "دانلود توکنایزر از سرور ممکن نشد." >&2
    fi
    cat >&2 <<EOF
فایل ${TOKENIZER_FILE} وجود ندارد. از ویندوز (PowerShell) یک‌بار بفرستید:
  scp .\\data\\tokenizer\\tokenizer.json production:${TOKENIZER_FILE}
یا TOKENIZER_URL را به نشانی مستقیم tokenizer.json تنظیم کنید و دوباره اجرا کنید.
EOF
    exit 1
}

verify_tokenizer() {
    if [[ -n "${TOKENIZER_SHA256:-}" ]] && ! echo "${TOKENIZER_SHA256}  ${TOKENIZER_FILE}" | sha256sum -c --quiet -; then
        echo "هش tokenizer.json با TOKENIZER_SHA256 یکی نیست؛ فایل را دوباره بفرستید." >&2
        exit 1
    fi
}

# مالکیت پوشه‌ی خروجی برای کاربر داخل کانتینر (uid ثابت ایمیج) و برگرداندنش به کاربر سرور در پایان
chown_run_dir() {
    compose run --rm --no-deps -T --user root -v "${RUN_DIR}:/fix" --entrypoint chown backend_api -R "$1" /fix
}

run_in_backend() {
    compose run --rm --no-deps -T \
        -v "${RUN_DIR}:/out" \
        -v "${TOKENIZER_DIR}:/tokenizer:ro" \
        backend_api "$@"
}

restore_owner() {
    if ! chown_run_dir "$(id -u):$(id -g)" >/dev/null 2>&1; then
        echo "هشدار: مالکیت ${RUN_DIR} برنگشت؛ با این دستور درستش کنید: sudo chown -R $(id -u):$(id -g) ${RUN_DIR}" >&2
    fi
}

ensure_tokenizer
verify_tokenizer
mkdir -p "${RUN_DIR}"
chmod 700 "${DATASETS_DIR}" "${RUN_DIR}"
chown_run_dir "${CONTAINER_UID}:${CONTAINER_UID}"
trap restore_owner EXIT

echo "━━━ ساخت دیتاست ━━━"
set +e
run_in_backend python -m app.datasets.finetune.build --out /out/dataset --tokenizer /tokenizer/tokenizer.json \
    --max-tokens "${MAX_TOKENS}" "$@"
BUILD_EXIT=$?
set -e
if [[ ${BUILD_EXIT} -eq 2 ]]; then
    echo "تعداد جفت‌های واجد شرایط کمتر از --min-pairs است؛ هیچ داده‌ای نوشته نشد." >&2
    exit 2
elif [[ ${BUILD_EXIT} -ne 0 ]]; then
    echo "ساخت دیتاست ناموفق بود (کد ${BUILD_EXIT})." >&2
    exit "${BUILD_EXIT}"
fi

echo "━━━ اعتبارسنجی ━━━"
set +e
run_in_backend python -m app.datasets.finetune.validate /out/dataset --tokenizer /tokenizer/tokenizer.json \
    --max-tokens "${MAX_TOKENS}"
VALIDATE_EXIT=$?
set -e
if [[ ${VALIDATE_EXIT} -ne 0 ]]; then
    run_in_backend mv /out/dataset /out/dataset.FAILED
    echo "اعتبارسنجی رد شد؛ خروجی به ${RUN_DIR}/dataset.FAILED منتقل شد و نباید برای آموزش استفاده شود." >&2
    exit 1
fi

echo "خروجی: ${RUN_DIR}/dataset"
echo "برای آموزش فقط train/validation/test.jsonl و stats.json منتقل شود؛ manifest.json (هش شناسه‌ها) روی سرور بماند."
