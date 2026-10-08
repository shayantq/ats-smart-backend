#!/usr/bin/env bash
# =============================================================================
# میان‌بر Docker Compose برای سرور Production — همیشه هر دو فایل compose و
# فایل نسخه‌ی منتشرشده (release.env) را با هم بارگذاری می‌کند تا هر دستور دستی
# روی سرور دقیقاً همان ایمیج‌هایی را ببیند که آخرین استقرار موفق اجرا کرده.
#
#   ./deploy/compose.sh ps
#   ./deploy/compose.sh logs -f backend_api
#   ./deploy/compose.sh exec postgres_db psql -U ats smart_ats_db
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

RELEASE_ENV_FILE="${RELEASE_ENV_FILE:-deploy/release.env}"
# فایل رازها/تنظیمات سرور؛ قابل تغییر فقط برای تست محلی همین اسکریپت‌ها
ENV_FILE="${ENV_FILE:-.env}"

env_args=(--env-file "${ENV_FILE}")
if [[ -f "${RELEASE_ENV_FILE}" ]]; then
    env_args+=(--env-file "${RELEASE_ENV_FILE}")
fi

exec docker compose "${env_args[@]}" -f docker-compose.yml -f deploy/docker-compose.prod.yml "$@"
