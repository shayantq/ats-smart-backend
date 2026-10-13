#!/usr/bin/env bash
# =============================================================================
# تمرین بازیابی فاجعه (DR Drill) — اثبات خودکار معیارهای پذیرش:
#
#   ۱. بک‌آپ‌ها رمزنگاری‌شده در Offsite هستند (و بدون کلید خصوصی قابل‌خواندن نیستند)
#   ۲. با از دست رفتن کامل سرور، دیتابیس فقط از روی Offsite (بک‌آپ کامل + بک‌آپ‌های افزایشی)
#      در یک نمونه‌ی کاملاً جدید بازیابی می‌شود و هدررفت داده حداکثر ۱ ساعت است
#
# سناریو (سه نشانگر در جدول موقت dr_drill_markers):
#   A  ثبت قبل از بک‌آپ کامل
#   B  ثبت بعد از بک‌آپ کامل، قبل از بک‌آپ افزایشی ساعتی    ← فقط با WAL قابل بازیابی است
#   C  ثبت بعد از آخرین بک‌آپ افزایشی (لحظه‌ی فاجعه)          ← از دست رفتنش مجاز است (< ۱ ساعت)
#   انتظار پس از بازیابی: A و B موجود، C موجود نیست.
#
#   bash backup/dr_drill.sh          (از ریشه‌ی پروژه، با استک در حال اجرا)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
# Git Bash ویندوز: مسیرهای لینوکسی داخل دستورها (/data/...) به مسیر ویندوزی تبدیل نشوند
export MSYS_NO_PATHCONV=1

dc() { docker compose "$@"; }
sql() { dc exec -T postgres_db sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$0"' "$1"; }
step() { printf '\n\033[1;36m━━ %s\033[0m\n' "$*"; }
pass() { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m  ✘ %s\033[0m\n' "$*"; exit 1; }

started=$(date +%s)
SAMPLE=dr-drill-sample.pdf
cleanup() {
    sql "drop table if exists dr_drill_markers" > /dev/null 2>&1 || true
    dc exec -T backend_api rm -f "/app/media/resumes/${SAMPLE}" > /dev/null 2>&1 || true
}
trap cleanup EXIT

step "۰. آماده‌سازی: جدول نشانگرهای تمرین"
sql "drop table if exists dr_drill_markers; create table dr_drill_markers (marker text primary key, written_at timestamptz default now())" > /dev/null
pass "جدول dr_drill_markers ساخته شد"

step "۱. نشانگر A → بک‌آپ کامل (همان دستور شبانه‌ی ۰۲:۰۰)"
sql "insert into dr_drill_markers (marker) values ('A-before-full')" > /dev/null
dc exec -T backup ats-backup full

step "۲. نشانگر B → بک‌آپ افزایشی (همان دستور ساعتی)"
sql "insert into dr_drill_markers (marker) values ('B-after-full-before-hourly')" > /dev/null
dc exec -T backup ats-backup wal

step "۳. نشانگر C → لحظه‌ی فاجعه (بعد از آخرین بک‌آپ ساعتی؛ هرگز به Offsite نمی‌رسد)"
sql "insert into dr_drill_markers (marker) values ('C-after-last-hourly')" > /dev/null
sql "select marker, to_char(written_at at time zone 'Asia/Tehran', 'HH24:MI:SS') from dr_drill_markers order by marker" | sed 's/^/  /'

step "۳ب. یک فایل رزومه‌ی نمونه → بک‌آپ هفتگی رزومه‌ها"
dc exec -T backend_api sh -c "mkdir -p /app/media/resumes && cat > /app/media/resumes/${SAMPLE}" < loadtest/sample_resume.pdf
original_hash=$(sha256sum loadtest/sample_resume.pdf | cut -d' ' -f1)
dc exec -T backup ats-backup resumes

step "۴. محتوای سرور Offsite (رمزنگاری‌شده)"
dc exec -T offsite_storage sh -c 'cd /data/ats-backups && find . -type f | sort | tail -n 12 | sed "s/^/  /"'
header=$(dc exec -T offsite_storage sh -c 'f=$(find /data/ats-backups/full -name database.dump.zst.age | sort | tail -n 1); head -c 21 "$f"')
[[ "$header" == "age-encryption.org/v1" ]] && pass "سرآیند فایل‌ها: «$header» — رمزنگاری‌شده با age" || fail "فایل بک‌آپ رمزنگاری‌شده نیست"
if dc exec -T offsite_storage sh -c 'f=$(find /data/ats-backups/full -name database.dump.zst.age | sort | tail -n 1); zstd -d -c "$f" > /dev/null 2>&1'; then
    fail "فایل بدون کلید خصوصی قابل‌خواندن است!"
fi
pass "بدون کلید خصوصی حتی از حالت فشرده هم خارج نمی‌شود"

step "۵. فاجعه: بازیابی در یک نمونه‌ی PostgreSQL کاملاً جدید، فقط از روی Offsite"
result=$(dc run --rm backup_restore drill --sql \
    "select string_agg(marker, ',' order by marker) from dr_drill_markers" | tee /dev/stderr \
    | sed -n '/--- RESULT ---/{n;p}' | tr -d '\r')

step "۶. بررسی معیار پذیرش"
echo "  نشانگرهای بازیابی‌شده: ${result}"
[[ "$result" == *"A-before-full"* ]] || fail "A (پیش از بک‌آپ کامل) بازیابی نشد"
pass "A بازیابی شد — بک‌آپ کامل سالم است"
[[ "$result" == *"B-after-full-before-hourly"* ]] || fail "B (بک‌آپ افزایشی) بازیابی نشد"
pass "B بازیابی شد — بک‌آپ‌های افزایشی (WAL) روی بک‌آپ کامل اعمال شدند"
[[ "$result" != *"C-after-last-hourly"* ]] || fail "C نباید در Offsite باشد (سناریو نامعتبر)"
pass "C (ثبت‌شده پس از آخرین بک‌آپ ساعتی) از دست رفت — هدررفت داده محدود به بازه‌ی بک‌آپ ساعتی (حداکثر ۱ ساعت)"

step "۷. بازیابی فایل‌های رزومه از Offsite"
restored_hash=$(dc run --rm --entrypoint sh backup_restore -c \
    "ats-backup restore-resumes --target-dir /tmp/media >&2 && sha256sum /tmp/media/resumes/${SAMPLE}" \
    | cut -d' ' -f1 | tr -d '\r')
echo "  SHA-256 اصلی:      ${original_hash}"
echo "  SHA-256 بازیابی‌شده: ${restored_hash}"
[[ "$restored_hash" == "$original_hash" ]] || fail "فایل رزومه‌ی بازیابی‌شده با اصل یکسان نیست"
pass "فایل رزومه بیت‌به‌بیت سالم بازیابی شد"

printf '\n\033[1;32m[DR DRILL PASS] بازیابی کامل از Offsite با موفقیت انجام شد (%s ثانیه)\033[0m\n' "$(( $(date +%s) - started ))"
