#!/usr/bin/env bash
# =============================================================================
# دیتابیس موقعیت جغرافیایی IP برای تشخیص ورود مشکوک (app/core/geoip.py، app/core/sessions.py):
# DB-IP City Lite — رایگان، بدون کلید و حساب کاربری، مجوز CC BY 4.0 (https://db-ip.com).
#
#   bash deploy/geoip-update.sh            # فقط اگر فایل نیست یا بیش از ۳۵ روز از آن گذشته
#   FORCE=1 bash deploy/geoip-update.sh    # دانلود دوباره
#
# deploy.sh آن را بعد از هر استقرار در پس‌زمینه اجرا می‌کند (استقرار منتظر دانلود ~۶۰ مگابایتی نمی‌ماند).
# فایل جدید اتمیک جایگزین می‌شود و API بدون ری‌استارت حداکثر ۱۰ دقیقه بعد از آن استفاده می‌کند.
# شکست دانلود هیچ چیز را خراب نمی‌کند: فقط بررسی جغرافیایی تا دانلود بعدی غیرفعال یا با فایل قبلی می‌ماند.
# =============================================================================
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${PROJECT_DIR}/geoip"
TARGET="${DIR}/dbip-city-lite.mmdb"
mkdir -p "${DIR}"

if [[ -z "${FORCE:-}" && -s "${TARGET}" && -z "$(find "${TARGET}" -mtime +35 2>/dev/null)" ]]; then
    echo "[geoip] فایل به‌روز است: ${TARGET}"
    exit 0
fi

# اوایل هر ماه ممکن است فایل ماه جدید هنوز منتشر نشده باشد → ماه قبل
for month in "$(date -u +%Y-%m)" "$(date -u -d '-1 month' +%Y-%m)"; do
    url="https://download.db-ip.com/free/dbip-city-lite-${month}.mmdb.gz"
    echo "[geoip] دانلود ${url}"
    if curl -fsSL --retry 3 --max-time 900 -o "${TARGET}.gz.part" "${url}"         && gunzip -c "${TARGET}.gz.part" > "${TARGET}.part" && [[ -s "${TARGET}.part" ]]; then
        chmod 644 "${TARGET}.part"
        mv -f "${TARGET}.part" "${TARGET}"
        rm -f "${TARGET}.gz.part"
        echo "[geoip] به‌روز شد: DB-IP City Lite ${month} ($(du -h "${TARGET}" | cut -f1))"
        exit 0
    fi
done
rm -f "${TARGET}.gz.part" "${TARGET}.part"
echo "[geoip] هشدار: دانلود ناموفق بود — بررسی جغرافیایی ورود با فایل قبلی (در صورت وجود) ادامه می‌یابد" >&2
exit 1
