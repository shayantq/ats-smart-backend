#!/usr/bin/env bash
# =============================================================================
# میان‌بر Docker Compose برای سرور Production — همیشه هر دو فایل compose و
# فایل نسخه‌ی منتشرشده (release.env) را با هم بارگذاری می‌کند تا هر دستور دستی
# روی سرور دقیقاً همان ایمیج‌هایی را ببیند که آخرین استقرار موفق اجرا کرده.
#
#   ./deploy/compose.sh ps
#   ./deploy/compose.sh logs -f backend_api
#   ./deploy/compose.sh exec postgres_db psql -U ats smart_ats_db
#
# EDGE_NETWORK در .env (سرور مشترک با Reverse Proxy دیگر) ← deploy/docker-compose.edge.yml هم اضافه می‌شود.
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

compose_files=(-f docker-compose.yml -f deploy/docker-compose.prod.yml)
# سرور مشترک: Gateway پشت Reverse Proxy بیرونی و بدون پورت باز (deploy/docker-compose.edge.yml)
if grep -qE '^EDGE_NETWORK=.+' "${ENV_FILE}" 2>/dev/null; then
    compose_files+=(-f deploy/docker-compose.edge.yml)
fi

exec docker compose "${env_args[@]}" "${compose_files[@]}" "$@"
